#!/bin/bash
#SBATCH --partition=cpu-48h
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=t.ranasinghe@lancaster.ac.uk

python -m crawlers.mpp_scraper --out articles_mpp