import json
import sys


def generate_id(index):
    """Generate id like doc_001, doc_002"""
    return f"doc_{index:03d}"


def fix_ids(input_file, output_file):
    # Load JSON
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("JSON must be an array")

    # Reset IDs
    for i, item in enumerate(data, start=1):
        item["id"] = generate_id(i)

    # Save JSON
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"✅ IDs fixed. Saved to {output_file}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage:")
        print("python fix_ids.py input.json output.json")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    fix_ids(input_file, output_file)