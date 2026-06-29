package health

import "testing"

func TestStatusReturnsOK(t *testing.T) {
	if got := Status(); got != "ok" {
		t.Fatalf("Status() = %q, want %q", got, "ok")
	}
}
