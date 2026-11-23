import unittest

from callcenter_bot.privacy import mask_digits


class MaskTest(unittest.TestCase):
    def test_masks_personal_numbers_in_logs(self):
        self.assertEqual(mask_digits("081-234-5678"), "xxx-xxx-5678")
        self.assertEqual(mask_digits("เบอร์ 0812345678"), "เบอร์ xxxxxx5678")
        self.assertEqual(mask_digits("1234"), "xxxx")
        self.assertEqual(mask_digits("ออเดอร์ 123456"), "ออเดอร์ 123456")


if __name__ == "__main__":
    unittest.main()
