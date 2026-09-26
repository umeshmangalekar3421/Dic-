.PHONY: venv run quick test clean

venv:
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -r requirements.txt

run:
	.venv/bin/python run_project.py

quick:
	.venv/bin/python run_project.py --quick

test:
	.venv/bin/python tests/test_physics.py

clean:
	rm -rf data results/figures results/models results/liberty results/sta results/metrics.json
