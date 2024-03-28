# KRKN-AI
## Troubleshooting

- if receive import error from chromadb scroll-up and check in the stack trace if sqlite3 is mention,
if that's the case and you're using pyenv, remove the current python version install libsql3-devel (Fedora 
libsq3-devel) and reinstall the python version with pyenv, recreate the venv reinstall poetry reinstall dependencies
