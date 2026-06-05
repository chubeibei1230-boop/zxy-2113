import uuid
from datetime import date

from ..models import Certificate


def bulk_review(certificate_ids, action_type, remark, reviewer):
    updated = []
    errors = []
    for cert_id in certificate_ids:
        try:
            cert = Certificate.objects.get(pk=cert_id)
            if action_type == 'issue':
                if cert.status != Certificate.STATUS_PENDING:
                    errors.append({'certificate_id': cert_id, 'reason': f'当前状态为{cert.get_status_display()}，无法发证'})
                    continue
                cert.status = Certificate.STATUS_ISSUED
                cert.issued_date = date.today()
                cert.reviewed_by = reviewer
                cert.remark = remark
                if not cert.certificate_no:
                    cert.certificate_no = f'CERT-{uuid.uuid4().hex[:12].upper()}'
                cert.save()
                updated.append(cert)
            elif action_type == 'revoke':
                if cert.status != Certificate.STATUS_ISSUED:
                    errors.append({'certificate_id': cert_id, 'reason': f'当前状态为{cert.get_status_display()}，无法撤销'})
                    continue
                cert.status = Certificate.STATUS_REVOKED
                cert.reviewed_by = reviewer
                cert.remark = remark
                cert.save()
                updated.append(cert)
        except Certificate.DoesNotExist:
            errors.append({'certificate_id': cert_id, 'reason': '证书记录不存在'})
    return updated, errors
