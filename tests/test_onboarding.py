import unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/'frontend'
class OnboardingTests(unittest.TestCase):
 def test_no_provider_label(self):
  h=(P/'index.html').read_text()
  self.assertNotIn('Accesso tramite Amazon Cognito',h)
  self.assertIn('Accedi al tuo spazio',h)
 def test_tour_skippable_replayable(self):
  h=(P/'index.html').read_text();js=(P/'app.js').read_text()
  for i in ('tutorialSkip','tutorialNext','tutorialBack','replayTutorial','tutorialDialog'):
   self.assertIn('id="'+i+'"',h)
  self.assertIn('if(!tourSeen())startTour()',js)
  self.assertIn('markTourSeen()',js)
  self.assertIn('claims.sub',js)
 def test_cache_bumped(self):
  self.assertIn('moneta-static-v2.2.3',(P/'sw.js').read_text())

 def test_interactive_spotlight(self):
  h=(P/'index.html').read_text();js=(P/'app.js').read_text();css=(P/'styles.css').read_text()
  self.assertIn('id="tourSpotlight"',h)
  self.assertIn('navigate(item.target)',js)
  self.assertIn('layoutTourSpotlight',js)
  self.assertIn('tour-shield',css)
  self.assertIn('finishTour()',js)
