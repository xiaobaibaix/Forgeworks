import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fw_views


SHEET_SIZE = (900, 300)


def make_sheet(path, panels):
    image = Image.new('RGB', SHEET_SIZE, 'white')
    draw = ImageDraw.Draw(image)
    for left, right, color in panels:
        draw.rectangle([left, 20, right, SHEET_SIZE[1] - 20], fill=color)
    image.save(path)
    return str(path)


class CropPanelsTest(unittest.TestCase):
    def test_three_panels_are_cropped_at_gutters(self):
        with tempfile.TemporaryDirectory() as directory:
            sheet = make_sheet(Path(directory) / 'sheet.png', [
                (10, 290, 'black'), (310, 590, 'gray'), (610, 890, 'red')])
            result = fw_views.crop_panels(sheet, directory, 'threeView_overall')
            self.assertEqual(result['warnings'], [])
            for name in ('front', 'side', 'top'):
                crop_path = Path(result[name + 'Path'])
                self.assertTrue(crop_path.is_file(), name)
                with Image.open(crop_path) as crop:
                    self.assertEqual(crop.size, (300, 300))

    def test_missing_sheet_returns_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            result = fw_views.crop_panels(
                str(Path(directory) / 'nope.png'), directory, 'threeView_x')
            self.assertEqual(result['frontPath'], '')
            self.assertTrue(any('THREEVIEW_SHEET_MISSING' in item
                                for item in result['warnings']))

    def test_off_center_gutters_warn_but_still_crop(self):
        with tempfile.TemporaryDirectory() as directory:
            sheet = make_sheet(Path(directory) / 'sheet.png', [
                (10, 230, 'black'), (290, 620, 'gray'), (680, 890, 'red')])
            result = fw_views.crop_panels(sheet, directory, 'threeView_y')
            self.assertTrue(any('THREEVIEW_GUTTER_DEV' in item
                                for item in result['warnings']))
            self.assertTrue(Path(result['frontPath']).is_file())
            self.assertTrue(Path(result['topPath']).is_file())


class ProcessThreeViewTest(unittest.TestCase):
    def test_process_returns_sheet_and_crops(self):
        with tempfile.TemporaryDirectory() as directory:
            sheet = make_sheet(Path(directory) / 'sheet.png', [
                (10, 290, 'black'), (310, 590, 'gray'), (610, 890, 'red')])
            result = fw_views.process_three_view(sheet, directory, 'threeView_roof')
            self.assertEqual(result['sheetPath'], sheet)
            self.assertEqual(result['annotatedPath'], '')
            self.assertTrue(Path(result['sidePath']).is_file())

    def test_annotate_writes_taller_sheet(self):
        with tempfile.TemporaryDirectory() as directory:
            sheet = make_sheet(Path(directory) / 'sheet.png', [
                (10, 290, 'black'), (310, 590, 'gray'), (610, 890, 'red')])
            measure = {'role': 'wheel', 'sizeM': [4.0, 1.7, 0.7],
                       'forward': '+X', 'confidence': 0.7}
            result = fw_views.process_three_view(
                sheet, directory, 'threeView_wheel', measure=measure, annotate=True)
            annotated = Path(result['annotatedPath'])
            self.assertTrue(annotated.is_file())
            with Image.open(annotated) as image:
                self.assertGreater(image.height, SHEET_SIZE[1])

    def test_process_without_sheet_keeps_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            result = fw_views.process_three_view(
                str(Path(directory) / 'nope.png'), directory, 'threeView_x')
            self.assertEqual(result['frontPath'], '')
            self.assertTrue(result['warnings'])


if __name__ == '__main__':
    unittest.main()
