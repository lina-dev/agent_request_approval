package audit

import (
	"context"
	"strings"
	"testing"
)

func TestRecordCapturesProvenance(t *testing.T) {
	r := Build("c1",
		CaseInput{PolicyVersion: "v3"},
		Decision{Status: "APPROVE", Citations: []string{"M-01"}},
		Meta{ModelVersions: map[string]string{"adjudicator": "llama-3.3-70b@abc"},
			FinalActor: "agent", TraceID: "trace-xyz"})
	b, err := Marshal(r)
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	for _, want := range []string{"v3", "M-01", "llama-3.3-70b@abc", "agent", "trace-xyz"} {
		if !strings.Contains(s, want) {
			t.Fatalf("record missing %q: %s", want, s)
		}
	}
}

type memPutter struct {
	key  string
	body []byte
}

func (m *memPutter) Put(_ context.Context, key string, body []byte) error {
	m.key, m.body = key, body
	return nil
}

func TestPutUsesPerCaseKey(t *testing.T) {
	p := &memPutter{}
	r := Build("c9", CaseInput{}, Decision{Status: "DENY"}, Meta{FinalActor: "human"})
	if err := Put(context.Background(), p, r); err != nil {
		t.Fatal(err)
	}
	if p.key != "audit/c9.json" {
		t.Fatalf("key = %q, want audit/c9.json", p.key)
	}
	if !strings.Contains(string(p.body), "human") {
		t.Fatalf("body missing actor: %s", p.body)
	}
}
