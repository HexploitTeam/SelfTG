"""Dependency-free arithmetic evaluator used instead of `eval()`.

`eval(expr, {"__builtins__": {}})` is **not** a sandbox: any expression that can
reach `().__class__.__base__.__subclasses__()` can walk Python's object graph and
execute arbitrary code. `!cauto` fed expressions taken from *other people's*
group messages into it, so that was a remote code execution path.

`evaluate()` accepts only numeric literals, `+ - * / // % **`, unary `+`/`-` and
parentheses, and raises ValueError for everything else.

This module has no `setup()`/`__HELP__`: main.py imports it during the command
scan and registers nothing for it.
"""
import ast
import operator

_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

MAX_EXPRESSION_LENGTH = 200
# Guards against `9**9**9`, which would hang the event loop computing it.
MAX_EXPONENT = 256


def evaluate(expression):
    """Return the numeric value of `expression`, or raise ValueError."""
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("empty expression")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError("expression too long")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError("invalid syntax") from exc
    return _evaluate_node(tree.body)


def _evaluate_node(node):
    if isinstance(node, ast.Constant):
        # bool is a subclass of int; reject True/False/None/strings.
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("only numbers are allowed")
        return node.value

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ValueError("exponent too large")
        return _BINARY_OPS[type(node.op)](left, right)

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_evaluate_node(node.operand))

    raise ValueError("unsupported expression")
