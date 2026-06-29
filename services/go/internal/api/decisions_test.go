package api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
)

type fakeStore struct {
	created string
	err     error
}

func (f *fakeStore) Create(_ context.Context, id string, _ []byte) error {
	if f.err != nil {
		return f.err
	}
	f.created = id
	return nil
}

type fakeQueue struct {
	enq string
	err error
}

func (f *fakeQueue) Enqueue(_ context.Context, id string) error {
	if f.err != nil {
		return f.err
	}
	f.enq = id
	return nil
}

func post(h *Handler, body string) *httptest.ResponseRecorder {
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/decisions", bytes.NewBufferString(body))
	h.Decide(rr, req)
	return rr
}

const validBody = `{"case_id":"c1","documents":[{"uri":"s3://b/r.jpg"}],
"claim":{"amount":10,"currency":"USD"},"policy_version":"v3"}`

func TestDecideAcceptsAndEnqueues(t *testing.T) {
	st, q := &fakeStore{}, &fakeQueue{}
	rr := post(&Handler{Store: st, Queue: q}, validBody)
	if rr.Code != http.StatusAccepted {
		t.Fatalf("code = %d, want 202 (%s)", rr.Code, rr.Body.String())
	}
	var resp map[string]string
	_ = json.Unmarshal(rr.Body.Bytes(), &resp)
	if resp["case_id"] != "c1" || resp["status"] != "accepted" {
		t.Fatalf("unexpected response %v", resp)
	}
	if st.created != "c1" || q.enq != "c1" {
		t.Fatalf("store/queue not invoked: %q %q", st.created, q.enq)
	}
}

func TestDecideRejectsMissingCaseID(t *testing.T) {
	body := `{"documents":[],"claim":{"amount":1,"currency":"USD"},"policy_version":"v3"}`
	rr := post(&Handler{Store: &fakeStore{}, Queue: &fakeQueue{}}, body)
	if rr.Code != http.StatusBadRequest {
		t.Fatalf("code = %d, want 400", rr.Code)
	}
}

func TestDecideRejectsBadS3URI(t *testing.T) {
	body := `{"case_id":"c1","documents":[{"uri":"http://evil/x"}],
	"claim":{"amount":1,"currency":"USD"},"policy_version":"v3"}`
	rr := post(&Handler{Store: &fakeStore{}, Queue: &fakeQueue{}}, body)
	if rr.Code != http.StatusBadRequest {
		t.Fatalf("code = %d, want 400 for bad uri", rr.Code)
	}
}

func TestDecideRejectsPathTraversal(t *testing.T) {
	body := `{"case_id":"c1","documents":[{"uri":"s3://b/../etc/passwd"}],
	"claim":{"amount":1,"currency":"USD"},"policy_version":"v3"}`
	rr := post(&Handler{Store: &fakeStore{}, Queue: &fakeQueue{}}, body)
	if rr.Code != http.StatusBadRequest {
		t.Fatalf("code = %d, want 400 for traversal", rr.Code)
	}
}

func TestDecideStoreErrorIs500(t *testing.T) {
	st := &fakeStore{err: errors.New("db down")}
	rr := post(&Handler{Store: st, Queue: &fakeQueue{}}, validBody)
	if rr.Code != http.StatusInternalServerError {
		t.Fatalf("code = %d, want 500", rr.Code)
	}
}

func TestDecideRejectsNonPost(t *testing.T) {
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/decisions", nil)
	(&Handler{Store: &fakeStore{}, Queue: &fakeQueue{}}).Decide(rr, req)
	if rr.Code != http.StatusMethodNotAllowed {
		t.Fatalf("code = %d, want 405", rr.Code)
	}
}
