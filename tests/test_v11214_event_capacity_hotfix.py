from pathlib import Path
import ast


def test_event_occupied_statuses_restored_after_domain_refactor():
    path = Path('app/domain_services/events.py')
    source = path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    values = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'EVENT_OCCUPIED_STATUSES':
                    values = ast.literal_eval(node.value)
    assert values == {'registered', 'reserved', 'checked_in', 'attended'}
    assert 'EventRegistration.status.in_(EVENT_OCCUPIED_STATUSES)' in source


def test_hotfix_version_is_current():
    assert Path('VERSION.txt').read_text().strip() == '1.12.1.4'
    assert Path('VERSION_CHECK.txt').read_text().strip() == '1.12.1.4'
