import os
import argparse
import csv
import json

from io import StringIO

from simulator import ClusterSimulator, Task, TaskStatus


class SystemValidator:
    """
    Automated test validator that runs a batch of tasks through the ClusterSimulator
    and compares the actual execution results against expected outcomes.
    """

    def __init__(self, config_json_data, tasks_csv_data):
        self.config_data = config_json_data

        # Initialize the simulator directly from the provided JSON string
        self.simulator = ClusterSimulator(self.config_data)

        # Parse the CSV string into tasks
        self.tasks_data = self._parse_csv_data(tasks_csv_data)

    def _parse_csv_data(self, csv_string):
        tasks = []
        reader = csv.DictReader(StringIO(csv_string.strip()))

        for row in reader:
            # Parse lists and dictionaries safely from the CSV format
            req_datasets = (
                [d.strip() for d in row["req_datasets"].split(",")]
                if row.get("req_datasets")
                else []
            )
            req_props = (
                json.loads(row["req_props"].replace("'", '"'))
                if row.get("req_props")
                else {}
            )
            exp_nodes = (
                [n.strip() for n in row["expected_nodes"].split(",")]
                if row.get("expected_nodes")
                else []
            )
            exp_score = (
                float(row["expected_score"]) if row.get("expected_score") else None
            )
            exp_phase = (
                row["expected_rejection_phase"]
                if row.get("expected_rejection_phase")
                else None
            )

            tasks.append(
                {
                    "name": row["name"],
                    "issuer": row["issuer"],
                    "req_datasets": req_datasets,
                    "req_props": req_props,
                    "req_geo": row["req_geo"],
                    "expected": {
                        "status": row["expected_status"],
                        "assigned_nodes": exp_nodes,
                        "score": exp_score,
                        "rejection_phase": exp_phase,
                    },
                }
            )
        return tasks

    def run_validation(self):
        print(f"\n{'='*80}")
        print("AUTOMATED SYSTEM VALIDATION".center(80))
        print(f"{'='*80}")

        passed_tests = 0
        total_tests = len(self.tasks_data)

        for t_data in self.tasks_data:
            task = Task(
                name=t_data["name"],
                issuer=t_data["issuer"],
                req_datasets=t_data["req_datasets"],
                req_props=t_data["req_props"],
                req_geo=t_data["req_geo"],
            )

            self.simulator.assign_task(task)

            expected = t_data["expected"]
            exp_status = expected.get("status")
            exp_nodes = expected.get("assigned_nodes", [])
            exp_score = expected.get("score")
            exp_phase = expected.get("rejection_phase")

            errors = []

            # 1. Validate Status
            if task.status != exp_status:
                errors.append(
                    f"Status mismatch: Expected '{exp_status}', Got '{task.status}'"
                )

            # 2. Validate Completed Task Attributes
            if (
                exp_status == TaskStatus.COMPLETED
                and task.status == TaskStatus.COMPLETED
            ):
                # Verify that all assigned nodes calculated by the simulator fall within the expected nodes array
                unexpected_nodes = [
                    n for n in task.assigned_nodes if n not in exp_nodes
                ]
                if unexpected_nodes:
                    errors.append(
                        f"Node mismatch: Got unexpected nodes {unexpected_nodes}, expected them to be in {exp_nodes}"
                    )

                if exp_score is not None:
                    if abs(task.score - exp_score) > 0.01:
                        errors.append(
                            f"Score mismatch: Expected {exp_score:.2f}, Got {task.score:.2f}"
                        )

            # 3. Validate Rejected Task Attributes
            elif (
                exp_status == TaskStatus.REJECTED and task.status == TaskStatus.REJECTED
            ):
                if task.rejection_phase != exp_phase:
                    errors.append(
                        f"Rejection phase mismatch: Expected '{exp_phase}', Got '{task.rejection_phase}'"
                    )

            # Output results
            if not errors:
                print(f"[PASSED] Task: {task.name.ljust(22)}")
                passed_tests += 1
            else:
                print(f"[FAILED] Task: {task.name.ljust(22)}")
                for err in errors:
                    print(f"    └─ {err}")

        print(f"-" * 80)
        completion_rate = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
        print(
            f"Validation Summary: {passed_tests}/{total_tests} tests passed ({completion_rate:.1f}%)."
        )
        print(f"{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Run the Cluster Simulator Test Suite with a JSON config and a CSV task list."
    )
    # Require two inputs now
    parser.add_argument(
        "config_file", type=str, help="Path to the JSON cluster config file."
    )
    parser.add_argument("tasks_csv", type=str, help="Path to the CSV tasks file.")
    args = parser.parse_args()

    # Validate file existence
    if not os.path.isfile(args.config_file):
        print(f"Error: Configuration file '{args.config_file}' not found.")
        return
    if not os.path.isfile(args.tasks_csv):
        print(f"Error: Tasks CSV file '{args.tasks_csv}' not found.")
        return

    print(f"\n{'#'*80}")
    print(f"LOADING CONFIG: {os.path.basename(args.config_file)}".center(80))
    print(f"LOADING TASKS:  {os.path.basename(args.tasks_csv)}".center(80))
    print(f"{'#'*80}")

    try:
        # Load raw file contents
        with open(args.config_file, "r", encoding="utf-8") as f_config:
            config_data = f_config.read()

        with open(args.tasks_csv, "r", encoding="utf-8") as f_tasks:
            tasks_csv_data = f_tasks.read()

        # Run Validator
        validator = SystemValidator(config_data, tasks_csv_data)
        validator.run_validation()

    except Exception as e:
        print(f"[ERROR] Failed to run tests. Exception: {e}")


if __name__ == "__main__":
    main()
