.PHONY: venv run quick test lab clean

venv:
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -r requirements.txt

run:
	.venv/bin/python run_project.py

quick:
	.venv/bin/python run_project.py --quick

lab:
	.venv/bin/python cellforge.py lab --host 0.0.0.0 --port 8000

test:
	.venv/bin/python tests/test_physics.py
	.venv/bin/python tests/test_service.py

clean:
	rm -rf data results/figures results/models results/liberty results/sta results/metrics.json
