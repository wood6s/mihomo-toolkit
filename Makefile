.PHONY: check test

check:
	./tests/static-check.sh

test:
	python3 -m unittest discover -s tests -v
