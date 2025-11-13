#!/usr/bin/env python3
"""
Combined Analytics Runner

This script runs all the combined schedule analytics:
1. Combined Schedule Evaluator (LTP constraints, conflicts, group distributions)
2. Combined Constraint Verifier (detailed constraint checking)
3. Combined Conflict Analyzer (detailed conflict analysis)
"""

import os
import sys
import glob
from datetime import datetime

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

try:
    from combined_schedule_evaluator import CombinedScheduleEvaluator
    from combined_constraint_verifier import CombinedConstraintVerifier
    from combined_conflict_analyzer import CombinedConflictAnalyzer
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Please ensure all analytics modules are in the same directory")
    sys.exit(1)

class CombinedAnalyticsRunner:
    def __init__(self):
        self.analytics_dir = "src/data_analytics/combined_analytics"
        self.output_dir = "output"
        self.results = {}
        
    def find_latest_combined_schedule(self):
        """Find the most recent combined schedule."""
        combined_dirs = sorted(glob.glob(os.path.join(self.output_dir, 'combined_schedule_*')), reverse=True)
        
        if not combined_dirs:
            print("❌ No combined schedule directories found!")
            return None
        
        latest_dir = combined_dirs[0]
        print(f"📁 Using latest combined schedule: {latest_dir}")
        
        lab_csv = os.path.join(latest_dir, 'combined_lab_schedule.csv')
        theory_csv = os.path.join(latest_dir, 'combined_theory_schedule.csv')
        
        if not os.path.exists(lab_csv) or not os.path.exists(theory_csv):
            print(f"❌ Missing schedule files in {latest_dir}")
            return None
        
        return lab_csv, theory_csv
    
    def run_schedule_evaluator(self):
        """Run the comprehensive schedule evaluator."""
        print("\n" + "="*80)
        print("🔍 RUNNING COMBINED SCHEDULE EVALUATOR")
        print("="*80)
        
        try:
            evaluator = CombinedScheduleEvaluator()
            success = evaluator.run_evaluation()
            
            self.results['evaluator'] = {
                'success': success,
                'status': '✅ PASSED' if success else '❌ FAILED'
            }
            
            print(f"Schedule Evaluator: {self.results['evaluator']['status']}")
            return success
            
        except Exception as e:
            print(f"❌ Error in schedule evaluator: {e}")
            self.results['evaluator'] = {
                'success': False,
                'status': '❌ ERROR',
                'error': str(e)
            }
            return False
    
    def run_constraint_verifier(self):
        """Run the detailed constraint verifier."""
        print("\n" + "="*80)
        print("🔧 RUNNING CONSTRAINT VERIFIER")
        print("="*80)
        
        try:
            schedule_files = self.find_latest_combined_schedule()
            if not schedule_files:
                return False
            
            lab_path, theory_path = schedule_files
            
            verifier = CombinedConstraintVerifier(lab_path, theory_path)
            success, violations = verifier.generate_constraint_report()
            
            self.results['constraint_verifier'] = {
                'success': success,
                'status': '✅ PASSED' if success else '❌ FAILED',
                'violations_count': len(violations)
            }
            
            print(f"Constraint Verifier: {self.results['constraint_verifier']['status']}")
            print(f"Violations found: {len(violations)}")
            return success
            
        except Exception as e:
            print(f"❌ Error in constraint verifier: {e}")
            self.results['constraint_verifier'] = {
                'success': False,
                'status': '❌ ERROR',
                'error': str(e)
            }
            return False
    
    def run_conflict_analyzer(self):
        """Run the detailed conflict analyzer."""
        print("\n" + "="*80)
        print("⚡ RUNNING CONFLICT ANALYZER")
        print("="*80)
        
        try:
            schedule_files = self.find_latest_combined_schedule()
            if not schedule_files:
                return False
            
            lab_path, theory_path = schedule_files
            
            analyzer = CombinedConflictAnalyzer(lab_path, theory_path)
            success, conflicts = analyzer.generate_conflict_report()
            
            total_conflicts = sum(len(conflict_list) for conflict_list in conflicts.values())
            
            self.results['conflict_analyzer'] = {
                'success': success,
                'status': '✅ NO CONFLICTS' if success else '❌ CONFLICTS FOUND',
                'total_conflicts': total_conflicts,
                'conflict_breakdown': {k: len(v) for k, v in conflicts.items()}
            }
            
            print(f"Conflict Analyzer: {self.results['conflict_analyzer']['status']}")
            print(f"Total conflicts: {total_conflicts}")
            return success
            
        except Exception as e:
            print(f"❌ Error in conflict analyzer: {e}")
            self.results['conflict_analyzer'] = {
                'success': False,
                'status': '❌ ERROR',
                'error': str(e)
            }
            return False
    
    def generate_master_report(self):
        """Generate a master report combining all analytics results."""
        print("\n" + "="*80)
        print("📋 GENERATING MASTER ANALYTICS REPORT")
        print("="*80)
        
        os.makedirs(os.path.join(self.analytics_dir, 'reports'), exist_ok=True)
        report_path = os.path.join(self.analytics_dir, 'reports', 'master_analytics_report.txt')
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("COMBINED SCHEDULE MASTER ANALYTICS REPORT\n")
            f.write("=" * 60 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Executive Summary
            f.write("EXECUTIVE SUMMARY\n")
            f.write("-" * 20 + "\n")
            
            overall_success = all(
                result.get('success', False) 
                for result in self.results.values()
            )
            
            f.write(f"Overall Status: {'✅ PASSED' if overall_success else '❌ FAILED'}\n")
            f.write(f"Components Run: {len(self.results)}\n")
            f.write(f"Components Passed: {sum(1 for r in self.results.values() if r.get('success', False))}\n\n")
            
            # Detailed Results
            f.write("DETAILED RESULTS\n")
            f.write("-" * 20 + "\n\n")
            
            # Schedule Evaluator Results
            if 'evaluator' in self.results:
                f.write("1. SCHEDULE EVALUATOR\n")
                f.write(f"   Status: {self.results['evaluator']['status']}\n")
                if 'error' in self.results['evaluator']:
                    f.write(f"   Error: {self.results['evaluator']['error']}\n")
                f.write("\n")
            
            # Constraint Verifier Results
            if 'constraint_verifier' in self.results:
                f.write("2. CONSTRAINT VERIFIER\n")
                f.write(f"   Status: {self.results['constraint_verifier']['status']}\n")
                f.write(f"   Violations: {self.results['constraint_verifier'].get('violations_count', 'Unknown')}\n")
                if 'error' in self.results['constraint_verifier']:
                    f.write(f"   Error: {self.results['constraint_verifier']['error']}\n")
                f.write("\n")
            
            # Conflict Analyzer Results
            if 'conflict_analyzer' in self.results:
                f.write("3. CONFLICT ANALYZER\n")
                f.write(f"   Status: {self.results['conflict_analyzer']['status']}\n")
                f.write(f"   Total Conflicts: {self.results['conflict_analyzer'].get('total_conflicts', 'Unknown')}\n")
                
                breakdown = self.results['conflict_analyzer'].get('conflict_breakdown', {})
                if breakdown:
                    f.write("   Conflict Breakdown:\n")
                    for conflict_type, count in breakdown.items():
                        f.write(f"     - {conflict_type}: {count}\n")
                
                if 'error' in self.results['conflict_analyzer']:
                    f.write(f"   Error: {self.results['conflict_analyzer']['error']}\n")
                f.write("\n")
            
            # Recommendations
            f.write("RECOMMENDATIONS\n")
            f.write("-" * 15 + "\n")
            
            if overall_success:
                f.write("✅ The combined schedule appears to be well-formed and constraint-compliant.\n")
                f.write("✅ No major issues detected in the scheduling.\n")
            else:
                f.write("⚠️ Issues detected in the combined schedule:\n\n")
                
                for component, result in self.results.items():
                    if not result.get('success', False):
                        f.write(f"- {component.replace('_', ' ').title()}: {result['status']}\n")
                        
                        if component == 'constraint_verifier' and result.get('violations_count', 0) > 0:
                            f.write("  → Review constraint verification report for specific violations\n")
                        
                        if component == 'conflict_analyzer' and result.get('total_conflicts', 0) > 0:
                            f.write("  → Review conflict analysis report for detailed conflict information\n")
                        
                        if 'error' in result:
                            f.write(f"  → Technical error needs investigation: {result['error']}\n")
                        
                        f.write("\n")
            
            # File Locations
            f.write("GENERATED FILES\n")
            f.write("-" * 15 + "\n")
            f.write(f"Reports: {os.path.join(self.analytics_dir, 'reports')}\n")
            f.write(f"Visualizations: {os.path.join(self.analytics_dir, 'visualizations')}\n")
            f.write(f"Conflict Analysis: {os.path.join(self.analytics_dir, 'conflict_analysis')}\n")
            f.write(f"Group Distributions: {os.path.join(self.analytics_dir, 'group_distributions')}\n")
        
        print(f"✅ Master report saved to {report_path}")
        return overall_success
    
    def run_all_analytics(self):
        """Run all analytics components."""
        print("🚀 STARTING COMBINED SCHEDULE ANALYTICS")
        print("=" * 80)
        print(f"Analytics Directory: {self.analytics_dir}")
        print(f"Output Directory: {self.output_dir}")
        
        # Check if combined schedule exists
        if not self.find_latest_combined_schedule():
            print("❌ No combined schedule found. Please run the combined scheduler first.")
            return False
        
        # Run all components
        results = []
        
        print("\n📊 Running analytics components...")
        
        # 1. Schedule Evaluator
        results.append(self.run_schedule_evaluator())
        
        # 2. Constraint Verifier
        results.append(self.run_constraint_verifier())
        
        # 3. Conflict Analyzer
        results.append(self.run_conflict_analyzer())
        
        # Generate master report
        overall_success = self.generate_master_report()
        
        # Final summary
        print("\n" + "="*80)
        print("🎯 COMBINED ANALYTICS COMPLETE")
        print("="*80)
        
        passed_components = sum(1 for result in results if result)
        total_components = len(results)
        
        print(f"Overall Status: {'✅ PASSED' if overall_success else '❌ FAILED'}")
        print(f"Components: {passed_components}/{total_components} passed")
        
        print(f"\n📁 Results available in: {self.analytics_dir}")
        print("📋 Check the master report for detailed findings")
        
        return overall_success

def main():
    """Main function."""
    runner = CombinedAnalyticsRunner()
    success = runner.run_all_analytics()
    return 0 if success else 1

if __name__ == "__main__":
    exit(main()) 