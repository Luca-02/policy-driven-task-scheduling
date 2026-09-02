import os
import csv
import json
import argparse
from simulator import ClusterSimulator, Task

def generate_expected_results(config_path, input_csv_path):
    # Initialize the simulator with the provided configuration
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = f.read()

    simulator = ClusterSimulator(config_data)

    # Prepare the output CSV path
    input_dir, input_filename = os.path.split(input_csv_path)
    output_filename = f"expected_{input_filename}"
    output_path = os.path.join(input_dir, output_filename)

    with open(input_csv_path, "r", encoding="utf-8") as infile, \
         open(output_path, "w", encoding="utf-8", newline='') as outfile:

        reader = csv.DictReader(infile)
        
        # Define the fieldnames for the output CSV, including expected results
        fieldnames = [
            "name", "issuer", "req_datasets", "req_props", "req_geo",
            "expected_status", "expected_nodes", "expected_score", "expected_rejection_phase"
        ]
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            # Parse the required datasets and properties from the CSV row
            req_datasets = [d.strip() for d in row["req_datasets"].split(",")] if row.get("req_datasets") else []
            req_props = json.loads(row["req_props"].replace("'", '"')) if row.get("req_props") else {}

            task = Task(
                name=row["name"],
                issuer=row["issuer"],
                req_datasets=req_datasets,
                req_props=req_props,
                req_geo=row["req_geo"]
            )

            # Assign the task using the simulator to compute expected results
            simulator.assign_task(task)

            # Prepare the expected results for writing to the output CSV
            exp_nodes = ",".join(task.assigned_nodes) if task.assigned_nodes else ""
            exp_score = f"{task.score:.2f}" if task.score is not None else ""
            exp_phase = task.rejection_phase if task.rejection_phase else ""

            # Write the task details along with the expected results to the output CSV
            writer.writerow({
                "name": task.name,
                "issuer": task.issuer,
                "req_datasets": row.get("req_datasets", ""), 
                "req_props": row.get("req_props", ""),       
                "req_geo": task.req_geo,
                "expected_status": task.status,
                "expected_nodes": exp_nodes,
                "expected_score": exp_score,
                "expected_rejection_phase": exp_phase
            })

    return output_path

def main():
    parser = argparse.ArgumentParser(
        description="Generate expected validation results from raw tasks."
    )
    parser.add_argument("config_file", type=str, help="Path to the JSON cluster config file.")
    parser.add_argument("raw_tasks_csv", type=str, help="Path to the raw CSV tasks file.")
    args = parser.parse_args()

    if not os.path.isfile(args.config_file):
        print(f"[ERROR] Config file '{args.config_file}' not found.")
        return
    if not os.path.isfile(args.raw_tasks_csv):
        print(f"[ERROR] Tasks file '{args.raw_tasks_csv}' not found.")
        return

    print(f"\nGenerating expected results for '{os.path.basename(args.raw_tasks_csv)}'...")
    
    try:
        output_path = generate_expected_results(args.config_file, args.raw_tasks_csv)
        print(f"[SUCCESS] File generated successfully: {output_path}\n")
    except Exception as e:
        print(f"[ERROR] Error during generation: {e}\n")

if __name__ == "__main__":
    main()