pip install -r requirements.txt
# tests run in a container (see tests/run.sh), but installing their deps here too
# lets the editor resolve `pytest` and typecheck tests/
pip install -r tests/requirements.txt
