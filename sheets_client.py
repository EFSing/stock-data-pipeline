from __future__ import annotations

import base64
import json
import os
from typing import Iterable


class SheetsClient:
    def __init__(self):
        import gspread
        from google.oauth2.service_account import Credentials

        sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
        raw_credentials = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if not sheet_id or not raw_credentials:
            raise RuntimeError("缺少GOOGLE_SHEET_ID或GOOGLE_SERVICE_ACCOUNT_JSON")
        try:
            info = json.loads(raw_credentials)
        except json.JSONDecodeError:
            info = json.loads(base64.b64decode(raw_credentials).decode("utf-8"))
        credentials = Credentials.from_service_account_info(
            info,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.file",
            ],
        )
        self.book = gspread.authorize(credentials).open_by_key(sheet_id)

    def records(self, sheet_name: str) -> list[dict]:
        return self.book.worksheet(sheet_name).get_all_records(default_blank="")

    def config(self) -> dict:
        return {str(row["参数"]): row["值"] for row in self.records("参数设置") if row.get("参数")}

    @staticmethod
    def _clean(value):
        if value is None:
            return ""
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    def _replace(self, sheet_name: str, headers: list[str], records: Iterable[dict]) -> None:
        worksheet = self.book.worksheet(sheet_name)
        rows = [[self._clean(record.get(header)) for header in headers] for record in records]
        worksheet.batch_clear([f"A2:{gspread_col(len(headers))}"])
        if rows:
            worksheet.update(rows, "A2", value_input_option="USER_ENTERED")

    def _upsert(self, sheet_name: str, headers: list[str], incoming: Iterable[dict], key_fields: tuple[str, ...]) -> int:
        existing = self.records(sheet_name)
        incoming_rows = list(incoming)
        by_key = {tuple(str(row.get(field, "")) for field in key_fields): row for row in existing}
        for row in incoming_rows:
            by_key[tuple(str(row.get(field, "")) for field in key_fields)] = row
        ordered = sorted(by_key.values(), key=lambda row: tuple(str(row.get(field, "")) for field in key_fields))
        self._replace(sheet_name, headers, ordered)
        return len(incoming_rows)

    def upsert_latest(self, rows: Iterable[dict]) -> int:
        return self._upsert("最新行情", LATEST_HEADERS, rows, ("统一代码",))

    def upsert_history(self, sheet_name: str, rows: Iterable[dict]) -> int:
        return self._upsert(sheet_name, HISTORY_HEADERS, rows, ("统一代码", "交易日期"))

    def append_rows(self, sheet_name: str, headers: list[str], rows: Iterable[dict]) -> int:
        values = [[self._clean(row.get(header)) for header in headers] for row in rows]
        if values:
            self.book.worksheet(sheet_name).append_rows(values, value_input_option="USER_ENTERED")
        return len(values)


def gspread_col(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


LATEST_HEADERS = ["统一代码", "名称", "市场", "交易日期", "抓取时间", "正式收盘", "校验状态", "主数据源", "校验数据源", "开盘", "最高", "最低", "收盘", "昨收", "涨跌幅", "成交量", "成交额", "换手率", "收盘价差异", "成交量差异", "币种", "备注"]
HISTORY_HEADERS = ["统一代码", "名称", "市场", "交易日期", "复权方式", "数据源", "开盘", "最高", "最低", "收盘", "昨收", "涨跌幅", "成交量", "成交额", "换手率", "币种", "抓取时间"]
VALIDATION_HEADERS = ["抓取时间", "统一代码", "交易日期", "主数据源", "校验数据源", "主源收盘", "校验源收盘", "收盘价差异", "主源成交量", "校验源成交量", "成交量差异", "日期一致", "价格通过", "成交量通过", "校验状态", "说明"]
LOG_HEADERS = ["运行时间", "任务组", "市场", "统一代码", "执行状态", "新增／更新行数", "消息"]
