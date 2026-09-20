import json
import unittest

import numpy as np

from spatiallm import Layout
from spatiallm.inference import (
    layout_to_dict,
    layout_to_json,
    point_cloud_from_arrays,
)
from spatiallm.layout.entity import Bbox, Door, Wall, Window


class PointCloudArrayInterfaceTest(unittest.TestCase):
    def test_accepts_normalized_rgb_and_removes_non_finite_rows(self):
        points = np.array(
            [
                [1.0, 2.0, 3.0],
                [np.nan, 0.0, 0.0],
            ]
        )
        colors = np.array(
            [
                [1.0, 0.5, 0.0, 0.25],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )

        point_cloud = point_cloud_from_arrays(points, colors)

        np.testing.assert_allclose(np.asarray(point_cloud.points), [[1.0, 2.0, 3.0]])
        np.testing.assert_allclose(np.asarray(point_cloud.colors), [[1.0, 0.5, 0.0]])

    def test_missing_colors_become_black(self):
        point_cloud = point_cloud_from_arrays(np.array([[1.0, 2.0, 3.0]]))
        np.testing.assert_allclose(np.asarray(point_cloud.colors), [[0.0, 0.0, 0.0]])

    def test_accepts_packed_xyzrgb_array(self):
        xyzrgb = np.array([[1.0, 2.0, 3.0, 255.0, 128.0, 0.0]])
        point_cloud = point_cloud_from_arrays(xyzrgb)

        np.testing.assert_allclose(np.asarray(point_cloud.points), [[1.0, 2.0, 3.0]])
        np.testing.assert_allclose(
            np.asarray(point_cloud.colors),
            [[1.0, 128.0 / 255.0, 0.0]],
        )

    def test_rejects_invalid_shapes(self):
        with self.assertRaisesRegex(ValueError, "points must have shape"):
            point_cloud_from_arrays(np.array([1.0, 2.0, 3.0]))


class LayoutJsonInterfaceTest(unittest.TestCase):
    def setUp(self):
        self.layout = Layout()
        self.layout.walls.append(Wall(0, 0.2, 0.4, 0.0, 4.8, 0.4, 0.0, 2.7, 0.0))
        self.layout.doors.append(Door(0, 0, 2.1, 0.4, 1.05, 0.9, 2.1))
        self.layout.windows.append(Window(0, 0, 3.8, 0.4, 1.6, 1.2, 1.0))
        self.layout.bboxes.append(Bbox(0, "sofa", 3.4, 2.2, 0.45, 1.5708, 2, 0.9, 0.9))

    def test_layout_to_framework_dictionary(self):
        payload = layout_to_dict(
            self.layout,
            default_wall_thickness=0.12,
            precision=4,
        )

        self.assertEqual(payload["walls"][0]["id"], "wall_0")
        self.assertEqual(payload["walls"][0]["a"], [0.2, 0.4, 0.0])
        self.assertEqual(payload["walls"][0]["thickness"], 0.12)
        self.assertEqual(payload["doors"][0]["wall_id"], "wall_0")
        self.assertEqual(payload["windows"][0]["id"], "window_0")
        self.assertEqual(payload["objects"][0]["class_name"], "sofa")
        self.assertEqual(payload["objects"][0]["size"], [2.0, 0.9, 0.9])

    def test_layout_to_json_is_valid_json(self):
        payload = json.loads(layout_to_json(self.layout))
        self.assertEqual(set(payload), {"walls", "doors", "windows", "objects"})
        self.assertEqual(payload["objects"][0]["id"], "object_0")


if __name__ == "__main__":
    unittest.main()
