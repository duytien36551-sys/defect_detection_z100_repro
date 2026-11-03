#include <assert.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "netif/xadapter.h"
void eth_link_detect(struct netif *n);
#include "../firmware/v8_lwip.c"

enum {
    FRAME_BYTES = 640 * 640 * 3,
    RING_BYTES = 32768,
    MAX_PBUF_BYTES = 1460,
    CANARY = 0xD7
};

static struct tcp_pcb mock_listener;
static struct tcp_pcb mock_clients[2];
static unsigned client_count;
static uint64_t mock_ticks;
static struct {
    uint64_t before;
    unsigned pbuf_frees;
    unsigned xinput_calls;
    uint64_t delivered_chunks;
    uint64_t delivered_bytes;
    size_t max_chunk_bytes;
    size_t max_ring_bytes;
    unsigned ring_wraps;
    uint64_t after;
} counters;
#define pbuf_frees counters.pbuf_frees
#define xinput_calls counters.xinput_calls
#define delivered_chunks counters.delivered_chunks
#define delivered_bytes counters.delivered_bytes
#define max_chunk_bytes counters.max_chunk_bytes
#define max_ring_bytes counters.max_ring_bytes
#define ring_wraps counters.ring_wraps
static size_t source_total;
static size_t source_offset;
static size_t source_chunk_index;
static uint8_t source_salt;
static int source_send_fin;
static int source_fin_sent;
static int source_error;
static unsigned service_calls;
static size_t service_read_bytes[2];
static int service_read_failed[2];
static TransportSession first_session;
static tcp_err_fn first_error_callback;
static void *first_error_argument;
static struct tcp_pcb *first_client;
static struct tcp_pcb *second_client;
static struct {
    uint8_t before;
    uint8_t bytes[FRAME_BYTES];
    uint8_t after;
} sink;
static struct {
    uint8_t before;
    uint8_t bytes[MAX_PBUF_BYTES];
    uint8_t after;
} pbuf_payload;
static const size_t chunk_pattern[] = {1460u, 1u, 511u, 7u, 1024u, 73u, 899u, 37u};

static uint8_t expected_byte(size_t offset, uint8_t salt)
{
    uint64_t value = (uint64_t)offset * 37u +
                     (uint64_t)(offset >> 8) * 13u +
                     (uint64_t)(offset >> 16) * 19u +
                     (uint64_t)salt * 71u + 23u;
    return (uint8_t)value;
}

static size_t expected_chunks(size_t bytes)
{
    size_t index = 0u, total = 0u;
    while (bytes) {
        size_t n = chunk_pattern[index++ %
                                 (sizeof(chunk_pattern) / sizeof(chunk_pattern[0]))];
        if (n > bytes) n = bytes;
        bytes -= n;
        ++total;
    }
    return total;
}

void Xil_ExceptionInit(void) {}
int XScuGic_DeviceInitialize(uint32_t device_id)
{
    assert(device_id == XPAR_SCUGIC_SINGLE_DEVICE_ID);
    return XST_SUCCESS;
}
void XScuGic_DeviceInterruptHandler(void *device_id) { (void)device_id; }
void Xil_ExceptionRegisterHandler(uint32_t exception_id,
                                 Xil_ExceptionHandler handler, void *data)
{
    assert(exception_id == XIL_EXCEPTION_ID_IRQ_INT);
    assert(handler == XScuGic_DeviceInterruptHandler);
    assert((uintptr_t)data == XPAR_SCUGIC_SINGLE_DEVICE_ID);
}
void Xil_ExceptionEnableMask(uint32_t mask) { assert(mask == XIL_EXCEPTION_IRQ); }
void XTime_GetTime(XTime *time) { *time = mock_ticks++; }
void lwip_init(void) {}

struct netif *xemac_add(struct netif *n, const ip_addr_t *ip,
                        const ip_addr_t *mask, const ip_addr_t *gw,
                        unsigned char *mac, uint32_t base)
{
    assert(n && ip && mask && gw && mac && base == XPAR_XEMACPS_0_BASEADDR);
    return n;
}
void netif_set_default(struct netif *n) { assert(n == &net); }
void netif_set_up(struct netif *n) { assert(n == &net); }

static err_t deliver_chunk(size_t bytes)
{
    struct pbuf packet;
    size_t i, old_len = incoming_len;
    if (!peer || !peer->recv || bytes == 0u || bytes > MAX_PBUF_BYTES ||
        source_offset > source_total || bytes > source_total - source_offset) {
        source_error = 1;
        return ERR_ABRT;
    }
    pbuf_payload.before = CANARY;
    pbuf_payload.after = CANARY;
    for (i = 0; i < bytes; ++i)
        pbuf_payload.bytes[i] = expected_byte(source_offset + i, source_salt);
    packet.next = 0;
    packet.payload = pbuf_payload.bytes;
    packet.len = (u16_t)bytes;
    packet.tot_len = (u16_t)bytes;
    if (bytes > max_chunk_bytes) max_chunk_bytes = bytes;
    if (old_len + bytes > max_ring_bytes) max_ring_bytes = old_len + bytes;
    if (peer->recv(peer->arg, peer, &packet, ERR_OK) != ERR_OK) {
        source_error = 1;
        return ERR_ABRT;
    }
    if (pbuf_payload.before != CANARY || pbuf_payload.after != CANARY ||
        incoming_head >= RING_BYTES || incoming_len > RING_BYTES) {
        source_error = 1;
        return ERR_ABRT;
    }
    source_offset += bytes;
    ++delivered_chunks;
    delivered_bytes += bytes;
    return ERR_OK;
}

void xemacif_input(struct netif *n)
{
    size_t nbytes;
    assert(n == &net);
    ++xinput_calls;
    if (!peer || source_error) return;
    if (source_offset < source_total) {
        nbytes = chunk_pattern[source_chunk_index++ %
                               (sizeof(chunk_pattern) / sizeof(chunk_pattern[0]))];
        if (nbytes > source_total - source_offset)
            nbytes = source_total - source_offset;
        (void)deliver_chunk(nbytes);
    } else if (source_send_fin && !source_fin_sent) {
        source_fin_sent = 1;
        (void)peer->recv(peer->arg, peer, 0, ERR_OK);
    }
}

void eth_link_detect(struct netif *n) { assert(n == &net); }
struct tcp_pcb *tcp_new(void)
{
    memset(&mock_listener, 0, sizeof(mock_listener));
    return &mock_listener;
}
err_t tcp_bind(struct tcp_pcb *pcb, const void *address, uint16_t port)
{
    assert(pcb == &mock_listener && address == IP_ADDR_ANY && port == 5001u);
    return ERR_OK;
}
struct tcp_pcb *tcp_listen(struct tcp_pcb *pcb)
{
    assert(pcb == &mock_listener);
    return pcb;
}
void tcp_accept(struct tcp_pcb *pcb, tcp_accept_fn fn) { pcb->accept = fn; }
void tcp_arg(struct tcp_pcb *pcb, void *arg) { pcb->arg = arg; }
void tcp_recv(struct tcp_pcb *pcb, tcp_recv_fn fn) { pcb->recv = fn; }
void tcp_err(struct tcp_pcb *pcb, tcp_err_fn fn) { pcb->errf = fn; }
void tcp_abort(struct tcp_pcb *pcb) { ++pcb->aborted; }
err_t tcp_close(struct tcp_pcb *pcb) { ++pcb->closed; return ERR_OK; }
void tcp_recved(struct tcp_pcb *pcb, u16_t bytes) { pcb->received_bytes += bytes; }
void pbuf_free(struct pbuf *p) { (void)p; ++pbuf_frees; }
u16_t tcp_sndbuf(struct tcp_pcb *pcb) { (void)pcb; return 4096u; }
err_t tcp_write(struct tcp_pcb *pcb, const void *bytes, u16_t count, uint8_t flags)
{
    assert(flags == TCP_WRITE_FLAG_COPY);
    assert(pcb->output_len + count <= sizeof(pcb->output));
    memcpy(pcb->output + pcb->output_len, bytes, count);
    pcb->output_len += count;
    ++pcb->writes;
    return ERR_OK;
}
err_t tcp_output(struct tcp_pcb *pcb) { (void)pcb; return ERR_OK; }
void tcp_fasttmr(void) {}
void tcp_slowtmr(void) {}

static struct tcp_pcb *new_client(void)
{
    struct tcp_pcb *pcb;
    assert(client_count < sizeof(mock_clients) / sizeof(mock_clients[0]));
    pcb = &mock_clients[client_count++];
    memset(pcb, 0, sizeof(*pcb));
    return pcb;
}

static void begin_source(size_t bytes, uint8_t salt, int send_fin)
{
    source_total = bytes;
    source_offset = 0u;
    source_chunk_index = 0u;
    source_salt = salt;
    source_send_fin = send_fin;
    source_fin_sent = 0;
    source_error = 0;
    /* Reset the chunk schedule for each new TCP generation. */
}

static int verify_sink(size_t bytes, uint8_t salt)
{
    size_t i;
    if (sink.before != CANARY || sink.after != CANARY) return 0;
    for (i = 0; i < bytes; ++i)
        if (sink.bytes[i] != expected_byte(i, salt)) return 0;
    return 1;
}

int v8_service_one(V8Service *service)
{
    uint8_t chunk[4096];
    size_t total = 0u;
    unsigned call = service_calls++;
    int result = 0;
    assert(service && service->read && service->transport);
    sink.before = sink.after = CANARY;
    memset(sink.bytes, 0xCC, sizeof(sink.bytes));
    if (call == 0u) {
        first_session = *(TransportSession *)service->transport;
        first_client = first_session.pcb;
        assert(first_client == peer && first_session.generation != 0u);
        first_error_callback = first_client->errf;
        first_error_argument = first_client->arg;
    } else if (call == 1u) {
        TransportSession current = *(TransportSession *)service->transport;
        assert(current.pcb == peer && current.pcb == second_client);
        assert(current.generation != first_session.generation);
        assert(first_error_callback && first_error_argument);
        first_error_callback(first_error_argument, ERR_CONN);
        assert(peer == second_client);
        assert(net_write(&first_session, (const uint8_t *)"stale", 5u) == -1);
        assert(second_client->writes == 0u && second_client->output_len == 0u);
    } else {
        assert(!"unexpected inference callback");
    }

    while (total < FRAME_BYTES) {
        size_t before_head = incoming_head;
        size_t remaining = FRAME_BYTES - total;
        size_t capacity = remaining < sizeof(chunk) ? remaining : sizeof(chunk);
        int got = service->read(service->transport, chunk, capacity);
        if (incoming_head < before_head) ++ring_wraps;
        if (got <= 0) {
            result = -1;
            break;
        }
        if ((size_t)got > capacity || total > FRAME_BYTES - (size_t)got) {
            result = -2;
            break;
        }
        memcpy(sink.bytes + total, chunk, (size_t)got);
        total += (size_t)got;
    }
    service_read_bytes[call] = total;
    service_read_failed[call] = result != 0;
    if (!result && (total != FRAME_BYTES || !verify_sink(total, call == 0u ? 1u : 2u)))
        result = -3;
    if (result) service_read_failed[call] = 1;
    if (sink.before != CANARY || sink.after != CANARY) return -4;
    return result;
}

static int run_tests(void)
{
    V8Service service;
    size_t partial_bytes = 10031u;
    size_t chunks_before, frees_before;
    uint64_t bytes_before;
    uint64_t expected_full_chunks;

    memset(&service, 0, sizeof(service));
    memset(&counters, 0, sizeof(counters));
    counters.before = UINT64_C(0x123456789ABCDEF0);
    counters.after = UINT64_C(0x0FEDCBA987654321);
    if (sizeof(incoming) != RING_BYTES) return 7;
    if (v8_network_start(&service) != 0 || !mock_listener.accept) return 1;

    first_client = new_client();
    if (mock_listener.accept(mock_listener.arg, first_client, ERR_OK) != ERR_OK)
        return 2;
    begin_source(partial_bytes, 1u, 1);
    v8_network_pump();
    if (service_calls != 1u || !service_read_failed[0] ||
        service_read_bytes[0] != partial_bytes || first_client->closed != 1u ||
        first_client->aborted || peer || incoming_head || incoming_len || peer_eof ||
        first_client->received_bytes != partial_bytes ||
        pbuf_frees != expected_chunks(partial_bytes) || source_error ||
        !verify_sink(partial_bytes, 1u))
        return 3;

    chunks_before = delivered_chunks;
    bytes_before = delivered_bytes;
    frees_before = pbuf_frees;
    second_client = new_client();
    if (mock_listener.accept(mock_listener.arg, second_client, ERR_OK) != ERR_OK ||
        peer != second_client || peer_session.generation == first_session.generation)
        return 4;
    begin_source(FRAME_BYTES, 2u, 0);
    v8_network_pump();
    expected_full_chunks = expected_chunks(FRAME_BYTES);
    if (service_calls != 2u || service_read_failed[1] ||
        service_read_bytes[1] != FRAME_BYTES || second_client->closed != 1u ||
        second_client->aborted || second_client->received_bytes != FRAME_BYTES ||
        delivered_chunks - chunks_before != expected_full_chunks ||
        delivered_bytes - bytes_before != FRAME_BYTES ||
        pbuf_frees - frees_before != expected_full_chunks || source_error ||
        !verify_sink(FRAME_BYTES, 2u) || !ring_wraps || max_chunk_bytes > 1460u ||
        max_chunk_bytes != 1460u || max_ring_bytes > RING_BYTES ||
        xinput_calls < expected_full_chunks || peer || incoming_head || incoming_len ||
        peer_eof || second_client->writes || second_client->output_len)
        return 5;

    if (counters.before != UINT64_C(0x123456789ABCDEF0) ||
        counters.after != UINT64_C(0x0FEDCBA987654321) ||
        pbuf_payload.before != CANARY || pbuf_payload.after != CANARY ||
        sink.before != CANARY || sink.after != CANARY ||
        !service_read_failed[0] || service_read_failed[1])
        return 6;
    printf("PIN640 lwIP stream PASS: bytes=%u chunks=%" PRIu64 " wraps=%u max_ring=%lu\n",
           FRAME_BYTES, delivered_chunks, ring_wraps,
           (unsigned long)max_ring_bytes);
    return 0;
}

int main(void)
{
    int rc = run_tests();
    if (rc != 0) {
        fprintf(stderr,
                "network stream case %d failed: calls=%u chunks=%" PRIu64 " bytes=%" PRIu64 " frees=%u source_error=%d\n",
                rc, service_calls, delivered_chunks,
                delivered_bytes, pbuf_frees, source_error);
        return rc;
    }
    return 0;
}
