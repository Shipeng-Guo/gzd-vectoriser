#!/usr/bin/env python3
"""Behavioral regressions for the actual encoded wipe GIF; synthetic images only."""
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image, ImageDraw, ImageSequence
from make_comparison_gif import create_comparison

class ComparisonGIFTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root/'source.png'
        self.candidate = self.root/'candidate.png'
        a = Image.new('RGBA', (120, 80), (255,255,255,0))
        b = Image.new('RGBA', a.size, (255,255,255,255))
        ImageDraw.Draw(a).rectangle((10,10,109,69),fill=(220,20,40,255))
        ImageDraw.Draw(b).rectangle((10,10,109,69),fill=(20,80,220,255))
        a.save(self.source);b.save(self.candidate)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, **options):
        opts=dict(labels=False, fps=20, sweep_seconds=.4, hold_seconds=.1)
        opts.update(options)
        return create_comparison(self.source,self.candidate,self.root/'out',**opts)

    def test_decoded_wipe_endpoints_direction_duration_and_white(self):
        info=self.build()
        with Image.open(self.root/'out/comparison.gif') as gif:
            frames=[f.convert('RGB').copy() for f in ImageSequence.Iterator(gif)]
            self.assertEqual(gif.info.get('loop'),0)
        # 8 frames per sweep: 1 -> 0 -> 1. Test encoded full and half views.
        red,blue=(220,20,40),(20,80,220)
        self.assertEqual(frames[0].getpixel((30,30)),red)
        self.assertEqual(frames[8].getpixel((30,30)),blue)
        for i in (4,12):
            self.assertEqual(frames[i].getpixel((30,30)),red)
            self.assertEqual(frames[i].getpixel((90,30)),blue)
        for frame in frames:
            self.assertEqual(frame.getpixel((0,0)),(255,255,255))
            self.assertEqual(frame.getpixel((119,79)),(255,255,255))
        self.assertEqual(info['duration_ms'],900)
        self.assertEqual(info['encoded_frames'],16)
        self.assertTrue((self.root/'out/check.png').is_file())

    def test_shared_crop_and_resize(self):
        info=self.build(crop=[10,10,110,70],width=200)
        self.assertEqual((info['width'],info['height']),(200,120))
        with Image.open(self.root/'out/comparison.gif') as gif:
            self.assertEqual(gif.convert('RGB').getpixel((100,60)),(220,20,40))

    def test_dimension_mismatch_refused_before_output(self):
        Image.new('RGB',(121,80),'white').save(self.candidate)
        with self.assertRaisesRegex(ValueError,'identical registered'):
            self.build()
        self.assertFalse((self.root/'out').exists())

    def test_existing_output_and_invalid_crop_refused(self):
        (self.root/'out').mkdir()
        sentinel=self.root/'out/keep.txt';sentinel.write_text('keep')
        with self.assertRaisesRegex(ValueError,'already exists'):
            self.build()
        self.assertEqual(sentinel.read_text(),'keep')
        with self.assertRaisesRegex(ValueError,'Crop'):
            create_comparison(self.source,self.candidate,self.root/'other',
                              crop=[0,0,125,80],labels=False)

    def test_portable_labels_preview_and_input_immutability(self):
        before=[p.read_bytes() for p in (self.source,self.candidate)]
        info=self.build(width=600,labels=True,reference_label='<Source>',candidate_label='After & final')
        page=(self.root/'out/index.html').read_text()
        self.assertIn('&lt;Source&gt;',page)
        self.assertIn('After &amp; final',page)
        self.assertNotIn('<h1><Source>',page)
        self.assertEqual(before,[p.read_bytes() for p in (self.source,self.candidate)])
        self.assertEqual(info['decoded_check'],'passed')
        saved=json.loads((self.root/'out/animation.json').read_text())
        self.assertEqual(saved['reference_sha256'],info['reference_sha256'])

if __name__=='__main__':
    unittest.main(verbosity=2)
