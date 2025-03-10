"""
Clean pyproject.toml file from path dependencies for uv structure
"""

import toml
import sys


def remove_path_dependencies(pyproject_path):
    with open(pyproject_path, "r") as file:
        data = toml.load(file)
    
    # Check if we have a PEP 621 style project with dependencies
    if "project" in data and "dependencies" in data["project"]:
        dependencies = data["project"]["dependencies"]
        # For PEP 621, dependencies are a list, not a dict
        filtered_dependencies = []
        for dep in dependencies:
            # Check if this is a complex dependency with path specification
            if isinstance(dep, str) and " @ file://" in dep:
                # Skip path dependencies
                continue
            filtered_dependencies.append(dep)
        
        # Replace with filtered list
        data["project"]["dependencies"] = filtered_dependencies
    
    # Also handle optional dependencies if they exist
    if "project" in data and "optional-dependencies" in data["project"]:
        for group, deps in data["project"]["optional-dependencies"].items():
            filtered_group_deps = []
            for dep in deps:
                if isinstance(dep, str) and " @ file://" not in dep:
                    filtered_group_deps.append(dep)
            data["project"]["optional-dependencies"][group] = filtered_group_deps
    
    with open(pyproject_path, "w") as file:
        toml.dump(data, file)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python clean_pyproject_uv.py path/to/pyproject.toml")
        sys.exit(1)
    
    pyproject_path = sys.argv[1]
    remove_path_dependencies(pyproject_path)
    print(f"Successfully cleaned path dependencies from {pyproject_path}")