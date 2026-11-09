.PHONY: help inspect prepare backup verify test check
PYTHON ?= python3
CLI := scripts/sbm.py
.DEFAULT_GOAL := help
help:
	@echo 'System Backup Manager - commands:'
	@echo '  make inspect  - read-only target and RAID inspection'
	@echo '  make prepare  - destructive one-time HDD preparation (interactive)'
	@echo '  make backup   - clone Debian and dated snapshots'
	@echo '  make verify   - check clone and snapshots (not a boot test)'
	@echo '  make check    - syntax and local unit tests'
inspect:
	$(PYTHON) $(CLI) inspect
prepare:
	$(PYTHON) $(CLI) prepare
backup:
	$(PYTHON) $(CLI) backup
verify:
	$(PYTHON) $(CLI) verify
check: test
	$(PYTHON) -m py_compile $(CLI)
test:
	$(PYTHON) -m unittest discover -s tests -v
