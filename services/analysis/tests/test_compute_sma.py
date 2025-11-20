import unittest

from app import compute_sma


class TestComputeSMA(unittest.TestCase):
    def test_basic_window(self):
        values = [1, 2, 3, 4, 5]
        self.assertEqual(
            compute_sma(values, 3),
            [None, None, 2.0, 3.0, 4.0],
        )

    def test_window_one(self):
        values = [10, 20, 30]
        self.assertEqual(compute_sma(values, 1), [10.0, 20.0, 30.0])

    def test_window_larger_than_values(self):
        values = [5, 6]
        self.assertEqual(compute_sma(values, 5), [None, None])

    def test_invalid_window(self):
        with self.assertRaises(ValueError):
            compute_sma([1, 2, 3], 0)


if __name__ == "__main__":
    unittest.main()
