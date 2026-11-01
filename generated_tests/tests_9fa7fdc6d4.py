def test_divide_normal():
    divide(1.5, 1.5)

def test_divide_a_boundary():
    divide(0.0, 1.5)

def test_divide_a_invalid():
    raised = False
    try:
        divide('not-a-number', 1.5)
    except Exception:
        raised = True
    assert raised, 'Expected invalid input to raise an exception'

def test_divide_b_invalid():
    raised = False
    try:
        divide(1.5, 'not-a-number')
    except Exception:
        raised = True
    assert raised, 'Expected invalid input to raise an exception'

def test_divide_b_boundary_exception():
    raised = False
    try:
        divide(1.5, 0.0)
    except ValueError:
        raised = True
    assert raised, 'Expected ValueError for the boundary input'

def test_divide_regression_deterministic():
    first = divide(1.5, 1.5)
    second = divide(1.5, 1.5)
    assert first == second, 'Repeated calls with the same input should be deterministic'

def test_greet_normal():
    greet('friend')

def test_greet_name_boundary():
    greet('')

def test_greet_name_invalid():
    raised = False
    try:
        greet(17)
    except Exception:
        raised = True
    assert raised, 'Expected invalid input to raise an exception'

def test_greet_regression_deterministic():
    first = greet('friend')
    second = greet('friend')
    assert first == second, 'Repeated calls with the same input should be deterministic'
