import os
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from datalab_sdk import DatalabClient

load_dotenv()

api_key = os.getenv("DATALAB_API_KEY")
if not api_key:
    raise ValueError("DATALAB_API_KEY environment variable is not set")

client = DatalabClient(api_key=api_key)

print("Triggering pipeline and waiting for completion...")
execution = client.run_pipeline(
    pipeline_id="pl_Q08fMs-6I_G7",
    version=1,
    file_path=r"215497.pdf",
    output_format="html",
    max_polls=120,
    poll_interval=2,
)

print(f"Execution finished with status: {execution.status}")

if execution.status == "completed":
    for idx, step in enumerate(execution.steps):
        print(f"\n--- Step {idx} ({step.step_type}) Result ---")
        result = client.get_step_result(execution.execution_id, step_index=idx)
        
        html_content = result.get("html", "")
        if html_content:
            output_md_path = r"D:\GitHub\fuzzy-robot\tests\215497_result.md"
            with open(output_md_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"Saved HTML result to: {output_md_path}")
        else:
            print("No HTML content returned in step result.")
else:
    print(f"Execution failed or timed out: {execution}")