#include "native_row_command.h"
#include <string.h>
int zn_native_row_command(const ZnHaloGeometry *g,uint16_t first,uint16_t row,
    uint32_t epoch,uint32_t token,uint32_t tag,ZnRowCommand *out) {
    uint32_t xwords,plane,words,groups,segments,group32,ky;
    uint64_t run,first_token,last_token,first_tag,last_tag;
    ZnRowCommand c;
    if(!g || !out || !epoch || !g->input_channels || g->input_channels>1024 ||
       !g->input_height || g->input_height>640 || !g->input_width || g->input_width>640 ||
       !g->output_channels || g->output_channels>1024 || !g->output_height || g->output_height>640 ||
       !g->output_width || g->output_width>640 || !g->input_rows || !g->output_rows ||
       g->input_y+g->input_rows>g->input_height || g->output_y+g->output_rows>g->output_height ||
       row>=g->output_rows || first>=g->output_channels || first%32 ||
       (g->kernel!=1 && g->kernel!=3) || (g->stride!=1 && g->stride!=2) || g->padding>1)
       return -1;
    if((g->input_width+2*g->padding-g->kernel)/g->stride+1!=g->output_width ||
       (g->input_height+2*g->padding-g->kernel)/g->stride+1!=g->output_height) return -1;
    xwords=(g->input_width+15)/16;plane=g->input_rows*xwords;
    words=((g->input_channels+3)/4)*plane;groups=((g->input_channels+3)/4)*g->kernel*g->kernel;
    if(words>4096 || groups>1024) return -1;
    segments=(g->output_width+19)/20;group32=first/32;
    run=((uint64_t)group32*g->output_rows+row)*segments;
    first_token=token+run;last_token=first_token+segments-1;
    first_tag=tag+run*groups;last_tag=first_tag+(uint64_t)segments*groups-1;
    if(last_token>UINT32_MAX || last_tag>UINT32_MAX) return -1;
    memset(&c,0,sizeof(c));c.epoch=epoch;c.token_base=(uint32_t)first_token;c.tag_base=(uint32_t)first_tag;
    c.channels=g->input_channels;c.input_width=g->input_width;c.output_width=g->output_width;
    c.bank_words=(uint16_t)words;c.channel_plane_stride=(uint16_t)plane;
    c.kernel=g->kernel;c.stride=g->stride;c.padding=g->padding;
    c.lanes=(uint8_t)(g->output_channels-first>=32?32:g->output_channels-first);
    for(ky=0;ky<g->kernel;ky++) {
        int32_t y=(int32_t)(g->output_y+row)*g->stride-g->padding+(int32_t)ky;
        if(y>=0 && y<g->input_height) {
            int32_t local=y-g->input_y;
            if(local<0 || local>=g->input_rows) return -1;
            c.y_valid|=(uint8_t)(1u<<ky);
            c.ky_row_bases|=(uint64_t)((uint32_t)local*xwords)<<(14*ky);
        }
    }
    *out=c;return 0;
}
