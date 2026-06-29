package validate

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"
)

func contains(s []string, v string) bool {
	for _, x := range s {
		if x == v {
			return true
		}
	}
	return false
}

func TestMissingReceiptFlag(t *testing.T) {
	in := Input{Claim: Claim{AmountCents: 5000, Currency: "USD", Date: "2026-06-20"}}
	if got := Validate(in); !contains(got, "missing_receipt") {
		t.Fatalf("flags = %v, want missing_receipt", got)
	}
}

func TestAmountMismatchFlag(t *testing.T) {
	in := Input{
		Claim:    Claim{AmountCents: 5000, Currency: "USD", Date: "2026-06-20"},
		Receipts: []Receipt{{AmountCents: 4000, Date: "2026-06-20"}},
	}
	if got := Validate(in); !contains(got, "amount_mismatch") {
		t.Fatalf("flags = %v, want amount_mismatch", got)
	}
}

func TestDuplicateFlag(t *testing.T) {
	in := Input{
		Claim: Claim{AmountCents: 10000, Currency: "USD", Date: "2026-06-20"},
		Receipts: []Receipt{
			{AmountCents: 5000, Date: "2026-06-20"},
			{AmountCents: 5000, Date: "2026-06-20"},
		},
	}
	if got := Validate(in); !contains(got, "duplicate") {
		t.Fatalf("flags = %v, want duplicate", got)
	}
}

func TestMathFailOnNonPositiveClaim(t *testing.T) {
	in := Input{Claim: Claim{AmountCents: 0, Currency: "USD"},
		Receipts: []Receipt{{AmountCents: 0}}}
	if got := Validate(in); !contains(got, "math_fail") {
		t.Fatalf("flags = %v, want math_fail", got)
	}
}

func TestCleanCaseNoFlags(t *testing.T) {
	in := Input{
		Claim:    Claim{AmountCents: 5000, Currency: "USD", Date: "2026-06-20"},
		Receipts: []Receipt{{AmountCents: 5000, Date: "2026-06-20"}},
	}
	if got := Validate(in); !reflect.DeepEqual(got, []string{}) {
		t.Fatalf("flags = %v, want []", got)
	}
}

func TestValidateHTTP(t *testing.T) {
	body := `{"claim":{"amount_cents":5000,"currency":"USD","date":"2026-06-20"},"receipts":[]}`
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/validate", bytes.NewBufferString(body))
	Handler(rr, req)
	if rr.Code != http.StatusOK || !bytes.Contains(rr.Body.Bytes(), []byte("missing_receipt")) {
		t.Fatalf("got %d %s", rr.Code, rr.Body.String())
	}
}

func TestValidateHTTPRejectsBadJSON(t *testing.T) {
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/validate", bytes.NewBufferString("{bad"))
	Handler(rr, req)
	if rr.Code != http.StatusBadRequest {
		t.Fatalf("got %d, want 400", rr.Code)
	}
}
