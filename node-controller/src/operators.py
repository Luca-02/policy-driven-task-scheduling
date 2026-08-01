from abc import ABC, abstractmethod


class Operator(ABC):
    """Base class for all operators. Each subclass encapsulates its own logic."""

    name: str

    @abstractmethod
    def evaluate(self, node_values: str | None, values: list[str]) -> bool:
        """
        Evaluate the operator against the given node values and values.

        Args:
            node_values (str | None): The values of the node attributes corresponding to the condition's key.
                Can be None if the attribute is missing.
            values (list[str]): The list of values specified in the condition.

        Returns:
            bool: True if the condition is satisfied, False otherwise.
        """
        pass


class NumericOperator(Operator, ABC):
    """Base for operators that require integer comparison."""

    def _parse(self, node_values, values):
        try:
            return int(node_values), int(values[0])
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Operator {self.name} requires numeric values, "
                f"got node_value={type(node_values)}, value={type(values[0])}"
            ) from e


class ExistsOperator(Operator):
    name = "Exists"

    def evaluate(self, node_values, _):
        return node_values is not None


class NotExistsOperator(Operator):
    name = "NotExists"

    def evaluate(self, node_values, _):
        return node_values is None


class EqOperator(Operator):
    name = "Eq"

    def evaluate(self, node_values, values):
        return node_values is not None and node_values == values[0]


class NotEqOperator(Operator):
    name = "NotEq"

    def evaluate(self, node_values, values):
        return node_values is not None and node_values != values[0]


class InOperator(Operator):
    name = "In"

    def evaluate(self, node_values, values):
        return node_values is not None and node_values in values


class NotInOperator(Operator):
    name = "NotIn"

    def evaluate(self, node_values, values):
        return node_values is not None and node_values not in values


class GtOperator(NumericOperator):
    name = "Gt"

    def evaluate(self, node_values, values):
        if node_values is None or values is None:
            return False
        node_int, cmp_int = self._parse(node_values, values)
        return node_int > cmp_int


class LtOperator(NumericOperator):
    name = "Lt"

    def evaluate(self, node_values, values):
        if node_values is None or values is None:
            return False
        node_int, cmp_int = self._parse(node_values, values)
        return node_int < cmp_int


class GteOperator(NumericOperator):
    name = "Gte"

    def evaluate(self, node_values, values):
        if node_values is None or values is None:
            return False
        node_int, cmp_int = self._parse(node_values, values)
        return node_int >= cmp_int


class LteOperator(NumericOperator):
    name = "Lte"

    def evaluate(self, node_values, values):
        if node_values is None or values is None:
            return False
        node_int, cmp_int = self._parse(node_values, values)
        return node_int <= cmp_int
