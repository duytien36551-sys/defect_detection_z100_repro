#include "v8_service.h"
#include "v8_sha256.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WIRE_PROTOCOL "pin9-v8/2-input640"
#define MAX_FIELDS 16

typedef struct {
    char key[MAX_FIELDS][32];
    char value[MAX_FIELDS][129];
    unsigned count;
} Fields;

static int hex64(const char *s) {
    size_t i;
    if(!s || strlen(s)!=64)return 0;
    for(i=0;i<64;i++)if(!((s[i]>='0'&&s[i]<='9')||(s[i]>='a'&&s[i]<='f')))return 0;
    return 1;
}
static int class_contract(const V8Service*s){
    if(!s||!s->class_domain)return 0;
    return s->class_count==9u&&strcmp(s->class_domain,"pin")==0;
}
static int io_read(V8Service *s,uint8_t *p,size_t n){
    while(n){int got=s->read(s->transport,p,n);if(got<=0||(size_t)got>n)return -1;p+=got;n-=(size_t)got;}return 0;
}
static int io_read_tensor(V8Service *s,uint8_t *p,size_t n,V8Sha256Context *hash){
    while(n){
        int got=s->read(s->transport,p,n);
        if(got<=0||(size_t)got>n)return -1;
        if(v8_sha256_update(hash,p,(size_t)got))return -1;
        p+=(size_t)got;n-=(size_t)got;
    }
    return 0;
}
static int io_write(V8Service *s,const uint8_t *p,size_t n){
    while(n){int sent=s->write(s->transport,p,n);if(sent<=0||(size_t)sent>n)return -1;p+=sent;n-=(size_t)sent;}return 0;
}
static int receive_json(V8Service *s,char *buf,size_t cap){
    uint8_t length[4];size_t n;
    /* Zero is clean EOF only before any byte of the next frame prefix. */
    int first=s->read(s->transport,length,4);
    if(first==0)return 0;
    if(first<0||first>4)return -1;
    if(first<4&&io_read(s,length+first,4-(size_t)first))return -1;
    n=((size_t)length[0]<<24)|((size_t)length[1]<<16)|((size_t)length[2]<<8)|length[3];
    if(n==0||n>V8_SERVICE_MAX_REQUEST_JSON||n>=cap)return -2;
    if(io_read(s,(uint8_t*)buf,n))return -1;
    buf[n]=0;return (int)n;
}
static int send_json(V8Service *s,const char *buf,size_t length){
    uint8_t prefix[4];
    if(length==0||length>1048576u)return -1;
    prefix[0]=(uint8_t)(length>>24);prefix[1]=(uint8_t)(length>>16);
    prefix[2]=(uint8_t)(length>>8);prefix[3]=(uint8_t)length;
    return io_write(s,prefix,4)||io_write(s,(const uint8_t*)buf,length)?-1:0;
}
static void space(const char **p){while(**p==' '||**p=='\n'||**p=='\r'||**p=='\t')++*p;}
static int quoted(const char **p,char *out,size_t cap){
    size_t n=0;
    if(*(*p)++!='"')return -1;
    while(**p&&**p!='"'){
        unsigned char c=(unsigned char)**p;
        if(c<' '||c=='\\'||n+1>=cap)return -1;
        out[n++]=(char)c;++*p;
    }
    if(*(*p)++!='"')return -1;
    out[n]=0;return 0;
}
/* Strict flat JSON, plain string keys/values or unsigned decimal values.
 * All client-controlled protocol fields are ASCII without escapes. */
static int parse_fields(const char *text,Fields *fields){
    const char *p=text;unsigned i;
    memset(fields,0,sizeof(*fields));space(&p);
    if(*p++!='{')return -1;
    space(&p);
    if(*p=='}')return -1;
    for(;;){
        char *value;size_t n=0;
        if(fields->count>=MAX_FIELDS)return -1;
        i=fields->count;
        if(quoted(&p,fields->key[i],sizeof(fields->key[i])))return -1;
        for(unsigned j=0;j<i;j++)if(!strcmp(fields->key[j],fields->key[i]))return -1;
        space(&p);if(*p++!=':')return -1;space(&p);
        value=fields->value[i];
        if(*p=='"'){
            if(quoted(&p,value,sizeof(fields->value[i])))return -1;
        }else{
            while(*p>='0'&&*p<='9'){
                if(n+1>=sizeof(fields->value[i]))return -1;
                value[n++]=*p++;
            }
            if(!n)return -1;
            value[n]=0;
        }
        fields->count++;
        space(&p);
        if(*p=='}'){++p;space(&p);return *p==0?0:-1;}
        if(*p++!=',')return -1;
        space(&p);
    }
}
static const char *field(const Fields *f,const char *name){
    unsigned i;for(i=0;i<f->count;i++)if(!strcmp(f->key[i],name))return f->value[i];return NULL;
}
static int eq(const Fields *f,const char *name,const char *value){
    const char *v=field(f,name);return v&&strcmp(v,value)==0;
}
static int request_id_ok(const char *s){
    unsigned i;if(!s||strlen(s)!=32)return 0;
    for(i=0;i<32;i++)if(!((s[i]>='0'&&s[i]<='9')||(s[i]>='a'&&s[i]<='f')))return 0;
    return 1;
}
static int error_reply(V8Service *s,const char *request_id,const char *message){
    int n;
    if(request_id)
        n=snprintf(s->response,s->response_capacity,
            "{\"type\":\"ERROR\",\"protocol\":\"%s\",\"runtime\":\"board\",\"request_id\":\"%s\",\"message\":\"%s\"}",
            WIRE_PROTOCOL,request_id,message);
    else
        n=snprintf(s->response,s->response_capacity,
            "{\"type\":\"ERROR\",\"protocol\":\"%s\",\"message\":\"%s\"}",
            WIRE_PROTOCOL,message);
    if(n<0||(size_t)n>=s->response_capacity)return -1;
    return send_json(s,s->response,(size_t)n);
}
static float clamp(float v){return v<0?0:v>1?1:v;}

int v8_service_one(V8Service *s){
    char request[V8_SERVICE_MAX_REQUEST_JSON+1], digest[65];
    V8Sha256Context hash;
    Fields f;const char *request_id;size_t i,at;int n;
    if(!s||!s->verified_identity||!hex64(s->model_sha256)||!hex64(s->classes_sha256)||!class_contract(s)||
       !s->read||!s->write||!s->infer||!s->tensor||s->tensor_capacity<V8_SERVICE_TENSOR_BYTES||
       !s->detections||s->detection_capacity==0||s->detection_capacity>10000||
       !s->response||s->response_capacity<1024)return -1;
    n=receive_json(s,request,sizeof(request));
    if(n<=0||parse_fields(request,&f))return -2;
    if(!eq(&f,"type","HELLO")||!eq(&f,"protocol",WIRE_PROTOCOL)||
       !eq(&f,"model_sha256",s->model_sha256)||!eq(&f,"classes_sha256",s->classes_sha256)){
        error_reply(s,NULL,"V8 protocol/model/class identity mismatch");return -3;
    }
    n=snprintf(s->response,s->response_capacity,
        "{\"type\":\"HELLO_OK\",\"protocol\":\"%s\",\"runtime\":\"board\",\"model_sha256\":\"%s\",\"classes_sha256\":\"%s\",\"class_count\":%u,\"class_domain\":\"%s\",\"input\":\"rgb-u8-640-letterbox114\",\"box_space\":\"normalized-model-xyxy\"}",
        WIRE_PROTOCOL,s->model_sha256,s->classes_sha256,(unsigned)s->class_count,s->class_domain);
    if(n<0||(size_t)n>=s->response_capacity||send_json(s,s->response,(size_t)n))return -4;
    n=receive_json(s,request,sizeof(request));
    if(n==0)return V8_SERVICE_PROBE_ONLY; /* HELLO-only probe; no INFER bytes were received. */
    if(n<0||parse_fields(request,&f))return -5;
    request_id=field(&f,"request_id");
    if(!request_id_ok(request_id)||!eq(&f,"type","INFER")||!eq(&f,"protocol",WIRE_PROTOCOL)||
       !(eq(&f,"task","pcb")||eq(&f,"task","pin"))||
       !eq(&f,"tensor_bytes","1228800")||!hex64(field(&f,"tensor_sha256")))return -6;
    if(s->class_count==9u&&!eq(&f,"task",s->class_domain)){
        error_reply(s,request_id,"requested task does not match the single-domain model");return -14;
    }
    if(v8_sha256_init(&hash)||io_read_tensor(s,s->tensor,V8_SERVICE_TENSOR_BYTES,&hash)||
       v8_sha256_final_hex(&hash,digest))return -7;
    if(!eq(&f,"tensor_sha256",digest)){
        error_reply(s,request_id,"input checksum mismatch");return -8;
    }
    at=0;
    if(s->infer(s->inference,s->tensor,V8_SERVICE_TENSOR_BYTES,
                s->detections,s->detection_capacity,&at)||at>s->detection_capacity){
        error_reply(s,request_id,"board inference failed");return -9;
    }
    n=snprintf(s->response,s->response_capacity,
        "{\"type\":\"RESULT\",\"protocol\":\"%s\",\"runtime\":\"board\",\"request_id\":\"%s\",\"box_space\":\"normalized-model-xyxy\",\"detections\":[",
        WIRE_PROTOCOL,request_id);
    if(n<0||(size_t)n>=s->response_capacity)return -10;
    size_t used=(size_t)n;
    for(i=0;i<at;i++){
        const V8Detection *d=s->detections+i;
        if(d->class_id<0||(uint32_t)d->class_id>=s->class_count||!isfinite(d->score)||d->score<0||d->score>1||
           !isfinite(d->x1)||!isfinite(d->y1)||!isfinite(d->x2)||!isfinite(d->y2)||
           d->x2<d->x1||d->y2<d->y1){
            error_reply(s,request_id,"invalid detection output");return -11;
        }
        n=snprintf(s->response+used,s->response_capacity-used,
            "%s{\"class_id\":%d,\"score\":%.9g,\"xyxy\":[%.9g,%.9g,%.9g,%.9g]}",
            i?",":"",d->class_id,(double)d->score,(double)clamp(d->x1),
            (double)clamp(d->y1),(double)clamp(d->x2),(double)clamp(d->y2));
        if(n<0||(size_t)n>=s->response_capacity-used)return -12;
        used+=(size_t)n;
    }
    if(used+3>s->response_capacity)return -12;
    s->response[used++]=']';s->response[used++]='}';s->response[used]=0;
    return send_json(s,s->response,used)?-13:0;
}
