#!/usr/bin/env python3
"""Pulizia ESCLUSIVA degli stack bilancio previsti, con piano in sola lettura di default.

Non cancella mai gli stack moneta-* o altre risorse AWS non associate ai 3 stack.
"""
import argparse
import json
import subprocess
import sys

LEGACY = (
    ('bilancio-backend', 'eu-south-1'),
    ('bilancio-frontend', 'us-east-1'),
    ('bilancio-budget', 'us-east-1'),
)
RETAINED = {
    ('bilancio-backend', 'UserPool'): ('AWS::Cognito::UserPool', 'user_pool'),
    ('bilancio-backend', 'DataTable'): ('AWS::DynamoDB::Table', 'table'),
    ('bilancio-frontend', 'WebBucket'): ('AWS::S3::Bucket', 'bucket'),
}


def aws(*args, region=None, output='json', allow_missing=False):
    command = ['aws'] + list(args)
    if region:
        command += ['--region', region]
    if output:
        command += ['--output', output]
    cp = subprocess.run(command, text=True, capture_output=True)
    if cp.returncode:
        if allow_missing and 'does not exist' in cp.stderr:
            return None
        raise RuntimeError('Comando AWS fallito: ' + ' '.join(command) + '\n' + cp.stderr.strip())
    if output == 'json':
        return json.loads(cp.stdout) if cp.stdout.strip() else None
    return cp.stdout.strip()


def inventory():
    result = {}
    for name, region in LEGACY:
        stacks = aws('cloudformation', 'describe-stacks', '--stack-name', name,
                     region=region, allow_missing=True)
        if not stacks:
            print(f'[ASSENTE] {name} ({region})')
            continue
        status = stacks['Stacks'][0]['StackStatus']
        if status not in ('CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE', 'ROLLBACK_COMPLETE'):
            raise RuntimeError(f'Lo stack {name} è in stato {status}: intervenire manualmente, nessuna cancellazione.')
        resources = aws('cloudformation', 'list-stack-resources', '--stack-name', name, region=region)
        items = resources.get('StackResourceSummaries', [])
        print(f'\n[DA ELIMINARE] {name} ({region}), stato {status}:')
        for row in items:
            print('  -', row['LogicalResourceId'], row['ResourceType'], row.get('PhysicalResourceId', '-'))
        for (sname, logical), (expected_type, _kind) in RETAINED.items():
            if sname != name:
                continue
            for item in items:
                if item['LogicalResourceId'] == logical and item['ResourceType'] != expected_type:
                    raise RuntimeError(f'Tipo inatteso per {name}/{logical}: {item["ResourceType"]}')
        result[name] = {
            'region': region,
            'resources': {item['LogicalResourceId']: item for item in items
                          if item.get('PhysicalResourceId') and item.get('ResourceStatus') != 'DELETE_COMPLETE'},
        }
    return result


def retained_physical(inv, stack, logical):
    res = inv.get(stack, {}).get('resources', {}).get(logical)
    return res['PhysicalResourceId'] if res else None


def require_budget():
    stack = aws('cloudformation', 'describe-stacks', '--stack-name', 'moneta-budget',
                region='us-east-1', allow_missing=True)
    if not stack or stack['Stacks'][0]['StackStatus'] not in ('CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE'):
        raise RuntimeError('Prima crea moneta-budget con ./scripts/deploy_budget.sh EMAIL; la pulizia si ferma per non lasciare scoperti gli avvisi.')


def clean(inv):
    # Prima gli stack che usano le risorse. Il budget precedente si rimuove per ultimo.
    for stack_name, region in LEGACY:
        if stack_name not in inv:
            continue
        print(f'\nELIMINO stack {stack_name} ({region})...')
        aws('cloudformation', 'delete-stack', '--stack-name', stack_name, region=region)
        aws('cloudformation', 'wait', 'stack-delete-complete', '--stack-name', stack_name, region=region)
        print('Eliminato stack:', stack_name)

    # Retain nell'installazione legacy: CloudFormation non elimina questi oggetti da solo.
    bucket = retained_physical(inv, 'bilancio-frontend', 'WebBucket')
    if bucket:
        print('\nVERIFICO bucket trattenuto:', bucket)
        versioning = aws('s3api', 'get-bucket-versioning', '--bucket', bucket, region='us-east-1') or {}
        if versioning.get('Status') in ('Enabled', 'Suspended'):
            raise RuntimeError('Bucket S3 con versioning attivo/sospeso: interrompo prima di svuotarlo. Effettuare pulizia manuale delle versioni.')
        aws('s3', 'rm', 's3://' + bucket, '--recursive', region='us-east-1', output=None)
        aws('s3api', 'delete-bucket', '--bucket', bucket, region='us-east-1')
        print('Eliminato bucket S3:', bucket)

    user_pool = retained_physical(inv, 'bilancio-backend', 'UserPool')
    if user_pool:
        print('\nELIMINO user pool Cognito trattenuto:', user_pool)
        aws('cognito-idp', 'update-user-pool', '--user-pool-id', user_pool,
            '--deletion-protection', 'INACTIVE', region='eu-south-1')
        aws('cognito-idp', 'delete-user-pool', '--user-pool-id', user_pool, region='eu-south-1')
        print('Eliminato User Pool:', user_pool)

    table = retained_physical(inv, 'bilancio-backend', 'DataTable')
    if table:
        print('\nELIMINO tabella DynamoDB trattenuta:', table)
        aws('dynamodb', 'delete-table', '--table-name', table, region='eu-south-1')
        aws('dynamodb', 'wait', 'table-not-exists', '--table-name', table, region='eu-south-1')
        print('Eliminata tabella:', table)

    print('\nPULIZIA COMPLETATA. I tre vecchi stack non sono più attivi.')
    print('Verifica comunque dalla Console AWS eventuali risorse esterne ai tre stack.')


def main():
    parser = argparse.ArgumentParser(description='Anteprima e pulizia degli stack bilancio prima della nuova installazione Moneta')
    parser.add_argument('--execute', action='store_true', help='Esegue eliminazione irreversibile dopo le verifiche')
    parser.add_argument('--confirm-account', default='', help='Deve corrispondere esattamente all’Account ID a 12 cifre (richiesto con --execute)')
    args = parser.parse_args()
    account = aws('sts', 'get-caller-identity')['Account']
    print('Account AWS selezionato:', account)
    inv = inventory()
    if not inv:
        print('\nNon risultano stack legacy da eliminare. Nessuna operazione.')
        return
    print('\nATTENZIONE: distruzione definitiva di User Pool (utenti + MFA), tabella DynamoDB, bucket S3 e budget legacy.')
    print('Eventuali risorse con DeletionPolicy Retain saranno rimosse separatamente.')
    if not args.execute:
        print(f'\nANTEPRIMA SOLTANTO. Dopo aver creato moneta-budget, per eseguire:\n  python3 scripts/cleanup_legacy.py --execute --confirm-account {account}')
        return
    if len(args.confirm_account) != 12 or args.confirm_account != account:
        raise RuntimeError('Conferma account errata o assente: nessuna modifica effettuata.')
    require_budget()
    clean(inv)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, KeyError) as ex:
        print('ERRORE:', ex, file=sys.stderr)
        sys.exit(1)
