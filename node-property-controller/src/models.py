import src.operators as operators

_OPERATORS: dict[str, operators.Operator] = {
    op.name: op for op in [
        operators.ExistsOperator(), operators.NotExistsOperator(),
        operators.EqOperator(), operators.NotEqOperator(),
        operators.InOperator(), operators.NotInOperator(),
        operators.GtOperator(), operators.LtOperator(),
        operators.GteOperator(), operators.LteOperator(),
    ]
}


class Condition:
    """
    A single expression: key operator values.
    """
 
    def __init__(self, key: str, operator: str, values: list[str] | None = None):
        if operator not in _OPERATORS:
            raise ValueError(f"Unknown operator: {operator!r}")
        self.key = key
        self.operator = _OPERATORS[operator]
        self.values = values or []
 
    def evaluate(self, attributes: dict[str, str]) -> bool:
        """
        Evaluate the condition against the given attributes.

        Args:
            attributes (dict[str, str]): Dict of node attributes to evaluate against the condition.

        Returns:
            bool: True if the condition is satisfied, False otherwise.
        """
        node_value = attributes.get(self.key)
        return self.operator.evaluate(node_value, self.values)


class Clause:
    """
    A clause is a conjunction of conditions.
    e.g. (cond1 AND cond2 AND cond3) is satisfied iff all conditions are satisfied.
    """

    def __init__(self, conditions: list[Condition]):
        self.conditions: list[Condition] = conditions

    def evaluate(self, attributes: dict[str, str]) -> bool:
        """
        Evaluate the conjunction of conditions against the given attributes.

        Args:
            attributes (dict[str, str]): Dict of node attributes to evaluate against the clause conditions.

        Returns:
            bool: True if all conditions are satisfied, False otherwise.
        """
        return all(cond.evaluate(attributes) for cond in self.conditions)


class Level:
    """
    One level of a property with its DNF expression, disjunction of clauses.
    e.g. (cond1 AND cond2) OR (cond3) is satisfied iff at least one of the clauses is satisfied.
    """

    def __init__(self, level: int, clauses: list[Clause]):
        self.level: int = level
        self.clauses: list[Clause] = clauses

    def evaluate(self, attributes: dict[str, str]) -> bool:
        """
        Evaluate the DNF expression of the level against the given attributes.
        
        Args:
            attributes (dict[str, str]): Dict of node attributes to evaluate against the level's DNF expression.
            
        Returns:
            bool: True if the level's DNF expression is satisfied, False otherwise.
        """
        return any(clause.evaluate(attributes) for clause in self.clauses)


class Property:
    """
    A property with multiple levels, each defined by a DNF expression. 
    The highest satisfied level is returned.
    """

    def __init__(self, name: str, levels: list[Level]):
        self.name: str = name
        self.levels: list[Level] = levels

    def max_level(self, attributes: dict[str, str]) -> int:
        """
        Return the highest level satisfied by the given attributes.

        Args:
            attributes (dict[str, str]): Dict of node attributes to evaluate against the property levels.

        Returns:
            int: The highest satisfied level, or 0 if no level is satisfied.
        """
        satisfied = [lvl.level for lvl in self.levels if lvl.evaluate(attributes)]
        return max(satisfied, default=0)


class Node:
    """
    A node with a set of attributes. 
    The property levels are evaluated against these attributes.
    """

    def __init__(self, name: str, attributes: dict[str, str]):
        self.name: str = name
        self.attributes: dict[str, str] = attributes

    def evaluate_property(self, prop: Property) -> int:
        """
        Evaluate the given property against the node's attributes.

        Args:
            prop (Property): The property to evaluate.

        Returns:
            int: The highest satisfied level of the property.
        """
        return prop.max_level(self.attributes)
