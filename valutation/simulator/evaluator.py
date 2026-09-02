from simulator import TaskStatus


class ExperimentalEvaluator:
    """
    Handles the analysis of experimental results and report generation.
    """

    def __init__(self, task_history):
        self.task_history = task_history

    def get_statistics(self):
        stats = {
            "total_tasks": len(self.task_history),
            "completed": 0,
            "rejected": 0,
            "rejections_by_phase": {},
        }

        for task in self.task_history:
            if task.status == TaskStatus.COMPLETED:
                stats["completed"] += 1
            elif task.status == TaskStatus.REJECTED:
                stats["rejected"] += 1
                phase = task.rejection_phase
                stats["rejections_by_phase"][phase] = (
                    stats["rejections_by_phase"].get(phase, 0) + 1
                )

        return stats

    def print_detailed_report(self):
        print("\n" + "=" * 80)
        print("SIMULATION EXPERIMENTAL RESULTS".center(80))
        print("=" * 80)

        for task in self.task_history:
            if task.status == TaskStatus.COMPLETED:
                print(
                    f"[✓] Task: {task.name.ljust(22)} | Node: {task.assigned_node.ljust(5)} | Score: {task.score:.2f}"
                )
            else:
                print(
                    f"[✗] Task: {task.name.ljust(22)} | REJECTED at {task.rejection_phase.ljust(18)}"
                )
                print(f"    └─ Reason: {task.rejection_reason}")

        stats = self.get_statistics()
        print("-" * 80)

        completion_rate = (
            (stats["completed"] / stats["total_tasks"]) * 100
            if stats["total_tasks"] > 0
            else 0
        )
        print(
            f"Overall Statistics: {stats['completed']}/{stats['total_tasks']} Tasks Assigned ({completion_rate:.1f}%)"
        )

        if stats["rejected"] > 0:
            print("Rejection Breakdown:")
            for phase, count in stats["rejections_by_phase"].items():
                print(f"  - {phase}: {count}")
        print("=" * 80 + "\n")
