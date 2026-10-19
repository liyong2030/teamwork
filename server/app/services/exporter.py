"""统计导出（Excel / CSV）。

数值口径与看板完全一致，均取自 ``stats_service``，不另行计算。
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.services import stats_service
from app.utils.week import week_label

PEOPLE_HEADERS = [
    "姓名",
    "登录名",
    "部门",
    "是否应提交",
    "豁免原因",
    "状态",
    "提交时间",
    "是否有效",
    "连续未交周数",
]

DEPARTMENT_HEADERS = [
    "部门",
    "应提交",
    "豁免",
    "已提交",
    "准时",
    "迟到",
    "补交",
    "未交",
    "代交",
    "有效",
    "准时率(%)",
    "提交率(%)",
]


def build_report_rows(db: Session, week_start: dt.date, department_id: int | None = None) -> list[list[Any]]:
    """生成个人明细二维表（不含表头）。"""
    rows = stats_service.people(db, week_start=week_start, department_id=department_id)
    return [
        [
            row["full_name"],
            row["username"],
            row["department_name"] or "-",
            "是" if row["required"] else "否",
            row["exempt_reason"] or "",
            row["status_label"],
            row["submitted_at"] or "",
            "是" if row["is_valid"] else "否",
            row["continuous_missing"],
        ]
        for row in rows
    ]


def build_department_rows(
    db: Session, week_start: dt.date, department_ids: list[int] | None = None
) -> list[list[Any]]:
    """生成部门汇总二维表（不含表头）。"""
    rows = stats_service.by_department(
        db, week_start=week_start, department_ids=department_ids
    )
    return [
        [
            row["department_name"],
            row["required"],
            row["exempt"],
            row["submitted"],
            row["ontime"],
            row["late"],
            row["makeup"],
            row["missing"],
            row["by_proxy"],
            row["valid"],
            row["ontime_rate"],
            row["submit_rate"],
        ]
        for row in rows
    ]


def to_csv(headers: list[str], rows: list[list[Any]]) -> bytes:
    """导出 CSV（带 UTF-8 BOM，保证 Excel 打开不乱码）。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def to_xlsx(headers: list[str], rows: list[list[Any]], title: str = "周报统计") -> bytes:
    """导出 Excel（带表头样式与列宽自适应）。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31]

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="2F5597")
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in rows:
        sheet.append(row)

    # 列宽：按内容最大长度自适应，限制在 8~40
    for index, header in enumerate(headers, start=1):
        width = max(
            [len(str(header))] + [len(str(r[index - 1])) for r in rows if index - 1 < len(r)]
        )
        sheet.column_dimensions[get_column_letter(index)].width = min(max(width + 4, 10), 40)

    sheet.freeze_panes = "A2"
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def export_report(
    db: Session,
    *,
    week_start: dt.date,
    department_id: int | None = None,
    department_ids: list[int] | None = None,
    fmt: str = "xlsx",
    dimension: str = "people",
) -> tuple[bytes, str, str]:
    """统一导出入口。

    :return: (文件字节, 建议文件名, MIME 类型)
    """
    label = week_label(week_start)
    if dimension == "department":
        headers = DEPARTMENT_HEADERS
        rows = build_department_rows(db, week_start, department_ids)
        sheet_title = "部门汇总"
    else:
        headers = PEOPLE_HEADERS
        rows = build_report_rows(db, week_start, department_id)
        sheet_title = "个人明细"

    safe_date = week_start.isoformat()
    if fmt == "csv":
        return (
            to_csv(headers, rows),
            f"周报统计-{safe_date}-{dimension}.csv",
            "text/csv; charset=utf-8",
        )
    return (
        to_xlsx(headers, rows, title=sheet_title),
        f"周报统计-{safe_date}-{dimension}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
