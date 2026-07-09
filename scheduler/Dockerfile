FROM golang:1.24 AS build

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY cmd/ cmd/
COPY pkg/ pkg/
COPY internal/ internal/

RUN CGO_ENABLED=0 GOOS=linux go build -o /out/scheduler ./cmd

FROM gcr.io/distroless/static:nonroot
COPY --from=build /out/scheduler /scheduler

USER nonroot:nonroot

ENTRYPOINT ["/scheduler"]