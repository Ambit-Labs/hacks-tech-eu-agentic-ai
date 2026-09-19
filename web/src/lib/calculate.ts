/**
 * A tiny arithmetic evaluator for the `calculate` tool.
 *
 * It parses the expression itself instead of handing it to `eval` or
 * `new Function`, so a model can never run code through this path. Supported:
 * numbers, + - * / % ^, parentheses, unary minus.
 */

type Token = { kind: "number"; value: number } | { kind: "op"; value: string };

const OPERATORS = new Set(["+", "-", "*", "/", "%", "^", "(", ")"]);

function tokenize(input: string): Token[] {
  const tokens: Token[] = [];
  let index = 0;

  while (index < input.length) {
    const char = input[index];

    if (char === " " || char === "\t" || char === "\n" || char === "_" || char === ",") {
      index += 1;
      continue;
    }

    if (char >= "0" && char <= "9") {
      let end = index;
      while (end < input.length && input[end] >= "0" && input[end] <= "9") {
        end += 1;
      }
      if (input[end] === ".") {
        end += 1;
        while (end < input.length && input[end] >= "0" && input[end] <= "9") {
          end += 1;
        }
      }
      tokens.push({ kind: "number", value: Number(input.slice(index, end)) });
      index = end;
      continue;
    }

    if (char === ".") {
      let end = index + 1;
      while (end < input.length && input[end] >= "0" && input[end] <= "9") {
        end += 1;
      }
      if (end === index + 1) {
        throw new Error(`Unexpected "." at position ${index}.`);
      }
      tokens.push({ kind: "number", value: Number(input.slice(index, end)) });
      index = end;
      continue;
    }

    if (char === "x" || char === "×") {
      tokens.push({ kind: "op", value: "*" });
      index += 1;
      continue;
    }

    if (char === "÷") {
      tokens.push({ kind: "op", value: "/" });
      index += 1;
      continue;
    }

    if (OPERATORS.has(char)) {
      tokens.push({ kind: "op", value: char });
      index += 1;
      continue;
    }

    throw new Error(`Unsupported character "${char}" at position ${index}.`);
  }

  return tokens;
}

class Parser {
  private position = 0;

  constructor(private readonly tokens: Token[]) {}

  parse(): number {
    const value = this.parseSum();
    if (this.position < this.tokens.length) {
      throw new Error("Trailing input after a complete expression.");
    }
    return value;
  }

  private peek(): Token | undefined {
    return this.tokens[this.position];
  }

  private eatOperator(values: string[]): string | undefined {
    const token = this.peek();
    if (token?.kind === "op" && values.includes(token.value)) {
      this.position += 1;
      return token.value;
    }
    return undefined;
  }

  private parseSum(): number {
    let left = this.parseProduct();
    let operator = this.eatOperator(["+", "-"]);
    while (operator) {
      const right = this.parseProduct();
      left = operator === "+" ? left + right : left - right;
      operator = this.eatOperator(["+", "-"]);
    }
    return left;
  }

  private parseProduct(): number {
    let left = this.parsePower();
    let operator = this.eatOperator(["*", "/", "%"]);
    while (operator) {
      const right = this.parsePower();
      if ((operator === "/" || operator === "%") && right === 0) {
        throw new Error("Division by zero.");
      }
      if (operator === "*") {
        left *= right;
      } else if (operator === "/") {
        left /= right;
      } else {
        left %= right;
      }
      operator = this.eatOperator(["*", "/", "%"]);
    }
    return left;
  }

  private parsePower(): number {
    const base = this.parseUnary();
    if (this.eatOperator(["^"])) {
      // Right associative: 2^3^2 is 2^(3^2).
      return base ** this.parsePower();
    }
    return base;
  }

  private parseUnary(): number {
    const operator = this.eatOperator(["+", "-"]);
    if (operator) {
      const value = this.parseUnary();
      return operator === "-" ? -value : value;
    }
    return this.parsePrimary();
  }

  private parsePrimary(): number {
    const token = this.peek();

    if (!token) {
      throw new Error("Expression ended early.");
    }

    if (token.kind === "number") {
      this.position += 1;
      return token.value;
    }

    if (token.value === "(") {
      this.position += 1;
      const value = this.parseSum();
      if (!this.eatOperator([")"])) {
        throw new Error("Missing closing parenthesis.");
      }
      return value;
    }

    throw new Error(`Unexpected "${token.value}".`);
  }
}

const MAX_EXPRESSION_LENGTH = 200;

/** Evaluates an arithmetic expression. Throws on anything it cannot parse. */
export function calculateExpression(expression: string): number {
  if (expression.length > MAX_EXPRESSION_LENGTH) {
    throw new Error(`Expression is longer than ${MAX_EXPRESSION_LENGTH} characters.`);
  }

  const result = new Parser(tokenize(expression)).parse();

  if (!Number.isFinite(result)) {
    throw new Error("Result is not a finite number.");
  }

  return result;
}
