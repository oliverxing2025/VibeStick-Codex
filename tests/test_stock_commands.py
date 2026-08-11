import unittest

from unittest import mock

from vibe_stick.audio.stock_commands import parse_stock_command, resolve_stock_command


class StockCommandTests(unittest.TestCase):
    def test_add_known_stock(self) -> None:
        self.assertEqual(
            parse_stock_command("请帮我添加腾讯控股"),
            {
                "action": "add",
                "symbol": "hk00700",
                "name": "腾讯控股",
                "label": "添加腾讯控股",
            },
        )

    def test_delete_alias(self) -> None:
        command = parse_stock_command("删除工商银行")
        self.assertEqual(command["action"], "delete")
        self.assertEqual(command["symbol"], "sh601398")

    def test_us_stocks_are_not_supported(self) -> None:
        self.assertEqual(parse_stock_command("添加usAAPL")["action"], "unknown")

    def test_junzheng_group_alias(self) -> None:
        command = parse_stock_command("增加君正集团")
        self.assertEqual(command["action"], "add")
        self.assertEqual(command["symbol"], "sh601216")
        self.assertEqual(parse_stock_command("增加均正集团")["symbol"], "sh601216")
        self.assertEqual(parse_stock_command("增加军政集团")["symbol"], "sh601216")

    def test_sort_and_refresh(self) -> None:
        self.assertEqual(parse_stock_command("按跌幅排序")["sort"], "losers")
        self.assertEqual(parse_stock_command("恢复原始排序")["sort"], "custom")
        self.assertEqual(parse_stock_command("刷新行情")["action"], "refresh")

    def test_unknown_stock_does_not_guess(self) -> None:
        self.assertEqual(parse_stock_command("添加一家不存在的公司")["action"], "unknown")

    def test_online_a_share_fallback(self) -> None:
        with mock.patch(
            "vibe_stick.audio.stock_commands.lookup_a_share",
            return_value=("sh600519", "贵州茅台"),
        ) as lookup:
            command = resolve_stock_command("请帮我增加贵州茅台股票")
        self.assertEqual(command["action"], "add")
        self.assertEqual(command["symbol"], "sh600519")
        self.assertEqual(command["name"], "贵州茅台")
        lookup.assert_called_once_with("贵州茅台")

    def test_online_lookup_removes_spoken_fillers(self) -> None:
        with mock.patch(
            "vibe_stick.audio.stock_commands.lookup_a_share",
            return_value=("sh600519", "贵州茅台"),
        ) as lookup:
            command = resolve_stock_command("请帮我增加一个贵州茅台股票到自选股")
        self.assertEqual(command["symbol"], "sh600519")
        lookup.assert_called_once_with("贵州茅台")


if __name__ == "__main__":
    unittest.main()
