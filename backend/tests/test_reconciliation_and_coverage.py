from evidence.reconciliation import reconcile
from evidence.tabular import read_tabular
from documents import QUESTION_SPECS


def _book(name, csv):
    book = read_tabular(name, csv.encode())
    return book, book.sheets[0]


def test_no_fuzzy_dataset_join():
    a, sa = _book('inventory.csv', 'Dataset,Classification,System,Retention,Deletion Method,Owner\nalpha,High,A,30d,Erase,Bob\n')
    b, sb = _book('deletion.csv', 'Request,Dataset,Requested,Completed,Method,Validator,Status\nR1,beta,2026-01-01,2026-01-02,Erase,Bob,Completed\n')
    issues, unsupported = reconcile([('DATA_INVENTORY', a, sa), ('DATA_DELETION_RECORD', b, sb)])
    assert len(issues) == 1 and issues[0].identifier == 'beta'
    assert issues[0].source_file == 'deletion.csv' and issues[0].source_row == 2
    assert not unsupported


def test_missing_shared_key_never_guesses_join():
    a, sa = _book('assets.csv', 'Asset ID,Hostname,Environment,Criticality,EDR,Encryption\nA1,x,prod,high,yes,yes\n')
    b, sb = _book('endpoint.csv', 'Asset,Class,Expected,EDR Installed,Last Seen,Status\nA1,server,yes,yes,2026-01-01,ok\n')
    issues, unsupported = reconcile([('ASSET_INVENTORY', a, sa), ('ENDPOINT_PROTECTION_COVERAGE', b, sb)])
    assert not issues and len(unsupported) == 1


def test_coverage_is_not_misrepresented():
    assert len(QUESTION_SPECS) == 29
