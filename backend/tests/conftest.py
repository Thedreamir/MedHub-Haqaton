import os
import tempfile

# Тесты работают на временной БД, не трогая checkup_state.db разработчика.
os.environ["CHECKUP_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_state.db")
