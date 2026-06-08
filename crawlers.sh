#!/bin/bash
#SBATCH --partition=cpu-6h
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=t.ranasinghe@lancaster.ac.uk

python -m crawlers.ilovemithila_scraper.py --out articles