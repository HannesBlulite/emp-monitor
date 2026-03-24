"""Get actual AgentToken values from database."""
from monitoring.models import AgentToken

for t in AgentToken.objects.select_related('employee').all():
    print(f"{t.employee.display_name} | {t.token}")
