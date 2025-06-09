#!/usr/bin/env python3
"""
Run the theory grouping analysis to visualize course-group distribution.
"""

import os
import sys

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from src.data_analytics.analyze_theory_grouping import main as run_analysis

if __name__ == "__main__":
    run_analysis() 