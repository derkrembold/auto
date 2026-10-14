import pytest
from commission import run_test


class FakeClient:
    def __init__(self):
        self.values = []
        self.fault = False

    def check_status(self, motor):
        if self.fault:
            raise RuntimeError('Motor fault')

    def check_current(self):
        pass

    def speeds(self, values):
        self.values.append(tuple(values))

    def command(self, text):
        return 'OK ret=0 rpm=600'


def test_identification_moves_only_selected_wheel_and_ramps():
    client = FakeClient()
    run_test(client, 1, sleep=lambda _: None)
    assert all(left == 0 for left, _ in client.values)
    assert client.values[-5:] == [(0, 480), (0, 360), (0, 240), (0, 120), (0, 0)]


def test_fault_prevents_further_nonzero_commands():
    client = FakeClient()
    def sleep(_):
        client.fault = True
    with pytest.raises(RuntimeError, match='fault'):
        run_test(client, 0, sleep=sleep)
    assert client.values == [(0, 0), (600, 0)]
