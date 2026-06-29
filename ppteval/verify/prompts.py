RUBRIC_GEN_PROMPT_CONTEXT_TEMPLATE = """We are currently developing a benchmark to evaluate
Computer-Use Agents in {app_name}. As part of this we are generating a rubric tree of criteria to
evaluate whether the agent was successful in performing a task.

Here are some imports and class definitions that leaf node scorer functions will have access to:
```python
{python_context}
```
Besides these, the following packages are also installed and you may import them:
{available_packages}

Scorer functions will also have access to the following global variables:
```python
{global_variables}
```

Scorer functions will also have access to the following functions:
```python
{available_functions}
```
"""
