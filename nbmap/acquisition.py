"""A read-only acquisition task, independent of terminal input, output and exit codes."""
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .archive import RideArchive, count, ride_id
from .client import safe_error
from .summary import summarize
from .dataset import prepare_configured


def month_range(start, end):
    def parse(value):
        if not re.fullmatch(r'20\d{2}(0[1-9]|1[0-2])', value):
            raise ValueError('月份格式应为 YYYYMM，例如 202610。')
        return int(value[:4]) * 12 + int(value[4:]) - 1
    first, last = parse(start), parse(end)
    if first > last:
        raise ValueError('起始月份不能晚于结束月份。')
    return [f'{n // 12:04d}{n % 12 + 1:02d}' for n in range(first, last + 1)]


def collect_month(source, sn, month, archive, *, max_pages=100, refresh_details=False, retry_incomplete=False, progress=None):
    month_range(month, month)
    if max_pages < 1:
        raise ValueError('max_pages 必须大于 0')
    emit = progress or (lambda event: None)
    capture = archive.capture(month)
    rows, totals_seen, summary, errors = {}, [], {}, []
    stop, pages = 'max_pages', 0
    for page in range(1, max_pages + 1):
        try:
            payload = source.month(sn, month, page)
            capture.save_page(page, payload)
            pages += 1
            if isinstance(payload, dict) and payload.get('list') is None and count(payload.get('times')) == 0:
                payload = {**payload, 'list': []}
            if not isinstance(payload, dict) or not isinstance(payload.get('list'), list):
                raise ValueError('未知月度结构')
            ids = [ride_id(row) for row in payload['list']]
        except ValueError:
            stop = 'schema_error'
            errors.append({'stage': 'list', 'page': page, 'kind': 'schema_error'})
            break
        except (RuntimeError, OSError) as exc:
            stop = 'request_error'
            errors.append({'stage': 'list', 'page': page, 'kind': type(exc).__name__, 'message': safe_error(exc)})
            break
        if page == 1:
            summary = {k: v for k, v in payload.items() if k != 'list'}
        total = count(payload.get('times'))
        if total is not None:
            totals_seen.append(total)
        if not ids:
            stop = 'empty_page'
            break
        new_ids = set(ids) - rows.keys()
        for rid, row in zip(ids, payload['list']):
            rows[rid] = row
        emit({'kind': 'page', 'month': month, 'page': page, 'listed': len(rows)})
        if not new_ids:
            stop = 'repeated_page'
            break
        if total is not None and len(rows) >= total:
            stop = 'reported_total_reached'
            break
    total = count(summary.get('times'))
    stable = len(set(totals_seen)) <= 1
    complete = None if total is None else (len(rows) == total and stable and stop in ('reported_total_reached', 'empty_page'))
    for index, (rid, row) in enumerate(rows.items(), 1):
        detail, state = None, 'unavailable'
        try:
            detail, state = capture.detail(rid, lambda: source.detail(sn, rid), refresh_details, retry_incomplete)
        except (ValueError, RuntimeError, OSError) as exc:
            errors.append({'stage': 'detail', 'ride_id': rid, 'kind': type(exc).__name__, 'message': safe_error(exc)})
        capture.add(row, detail, state)
        if index % 20 == 0 or index == len(rows):
            emit({'kind': 'detail', 'month': month, 'completed': index, 'total': len(rows)})
    return capture.finish({'upstream_summary': summary, 'upstream_ride_count': total,
        'missing_listed_rides': max(0, total - len(rows)) if total is not None else None,
        'list_complete': complete, 'reported_total_stable': stable, 'pages_received': pages,
        'stop_reason': stop, 'errors': errors})


@dataclass(frozen=True)
class AcquisitionResult:
    reports: list
    summary: dict
    has_gaps: bool
    report_directory: str
    dataset_directory: str | None = None


def _has_gaps(report):
    return (report.get('published') is False or report['list_complete'] is not True or bool(report['detail_failures'])
            or bool(report['invalid_points']) or report['rides_with_coordinates'] < report['listed_rides'])


class Acquisition:
    """One operation for cross-month acquisition, checkpoints and offline report creation."""
    def __init__(self, source, archive: RideArchive):
        self.source, self.archive = source, archive

    def run(self, sn, start, end, *, max_pages=100, refresh_details=False, retry_incomplete=False,
            retry_incomplete_since=None, progress=None):
        months = month_range(start, end)
        if max_pages < 1:
            raise ValueError('max_pages 必须大于 0')
        emit = progress or (lambda event: None)
        reports, current = [], None
        task_id = uuid.uuid4().hex
        def checkpoint(status):
            self.archive.save_task({'schema_version': 1, 'task_id': task_id, 'status': status,
                'updated_at': datetime.now(timezone.utc).isoformat(), 'requested_months': months,
                'current_month': current, 'reports': reports})
        checkpoint('running')
        try:
            for current in months:
                checkpoint('running')
                report = collect_month(self.source, sn, current, self.archive, max_pages=max_pages,
                    refresh_details=refresh_details,
                    retry_incomplete=retry_incomplete and (retry_incomplete_since is None or current >= retry_incomplete_since),
                    progress=emit)
                reports.append(report)
                checkpoint('running')
                emit({'kind': 'month', 'month': current, 'report': report})
            summary = summarize(self.archive)
            # Failed captures leave the last prepared dataset and its pointer intact.
            dataset_directory = prepare_configured(self.archive) if all(r.get('published') for r in reports) else None
            gaps = any(_has_gaps(r) for r in reports)
            checkpoint('completed_with_gaps' if gaps else 'completed')
            return AcquisitionResult(reports, summary, gaps, str(self.archive.report_path()),
                                     str(dataset_directory) if dataset_directory else None)
        except BaseException as exc:
            # Preserve the original interruption if recording it also fails.
            try:
                checkpoint('interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed')
            except OSError:
                pass
            raise
