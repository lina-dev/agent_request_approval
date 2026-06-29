package expense

import (
	"context"
	"errors"
	"testing"
)

func TestWritebackCallsAdapter(t *testing.T) {
	rec := &RecordingAdapter{}
	err := Writeback(context.Background(), rec, "c1",
		Decision{Status: "APPROVE", Rationale: "ok", Citations: []string{"M-01"}})
	if err != nil {
		t.Fatal(err)
	}
	if rec.Last.Status != "APPROVE" || rec.LastCase != "c1" || rec.Calls != 1 {
		t.Fatalf("adapter not called correctly: %+v", rec)
	}
}

func TestWritebackRejectsBadStatus(t *testing.T) {
	rec := &RecordingAdapter{}
	err := Writeback(context.Background(), rec, "c1", Decision{Status: "MAYBE"})
	if !errors.Is(err, ErrInvalidDecision) {
		t.Fatalf("err = %v, want ErrInvalidDecision", err)
	}
	if rec.Calls != 0 {
		t.Fatalf("adapter should not be called on invalid decision")
	}
}

func TestWritebackRejectsEmptyCaseID(t *testing.T) {
	if err := Writeback(context.Background(), &RecordingAdapter{}, "",
		Decision{Status: "APPROVE"}); !errors.Is(err, ErrInvalidDecision) {
		t.Fatalf("err = %v, want ErrInvalidDecision", err)
	}
}
