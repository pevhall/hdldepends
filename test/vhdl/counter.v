
//-----------------------------------------------------
// Design Name : up_down_counter
// File Name   : up_down_counter.v
// Function    : Up down counter
// Coder       : Deepak Kumar Tala
//-----------------------------------------------------
module up_down_counter    (
cntr_o      ,  // Output of the counter
up_down_i  ,  // up_down_i control for counter
clk_i      ,  // clock input
rst_i       // rst_i input
);
//----------Output Ports--------------
output [7:0] cntr_o;
//------------Input Ports-------------- 
input [7:0] data;
input up_down_i, clk_i, rst_i;
//------------Internal Variables--------
reg [7:0] cntr_o;
//-------------Code Starts Here-------
always @(posedge clk_i)
if (rst_i) begin // active high rst_i
  cntr_o <= 8'b0 ;
end else if (up_down_i) begin
  cntr_o <= cntr_o + 1;
end else begin
  cntr_o <= cntr_o - 1;
end


axis_data_to_chdr #(
      .CHDR_W          (CHDR_W),
      .ITEM_W          (ITEM_W),
      .NIPC            (NIPC),
      .SYNC_CLKS       (0),
      .INFO_FIFO_SIZE  ($clog2(32)),
      .PYLD_FIFO_SIZE  ($clog2(32)),
      .MTU             (MTU),
      .SIDEBAND_AT_END (0)
    ) axis_data_to_chdr (
      .axis_chdr_clk      (rfnoc_chdr_clk),
      .axis_chdr_rst      (rfnoc_chdr_rst),
      .axis_data_clk      (axis_data_clk),
      .axis_data_rst      (axis_data_rst),
      .m_axis_chdr_tdata  (m_rfnoc_chdr_tdata[(0+i)*CHDR_W+:CHDR_W]),
      .m_axis_chdr_tlast  (m_rfnoc_chdr_tlast[0+i]),
      .m_axis_chdr_tvalid (m_rfnoc_chdr_tvalid[0+i]),
      .m_axis_chdr_tready (m_rfnoc_chdr_tready[0+i]),
      .s_axis_tdata       (s_out_axis_tdata[(ITEM_W*NIPC)*i+:(ITEM_W*NIPC)]),
      .s_axis_tkeep       (s_out_axis_tkeep[NIPC*i+:NIPC]),
      .s_axis_tlast       (s_out_axis_tlast[i]),
      .s_axis_tvalid      (s_out_axis_tvalid[i]),
      .s_axis_tready      (s_out_axis_tready[i]),
      .s_axis_ttimestamp  (s_out_axis_ttimestamp[64*i+:64]),
      .s_axis_thas_time   (s_out_axis_thas_time[i]),
      .s_axis_tlength     (s_out_axis_tlength[16*i+:16]),
      .s_axis_teov        (s_out_axis_teov[i]),
      .s_axis_teob        (s_out_axis_teob[i]),
      .flush_en           (data_o_flush_en),
      .flush_timeout      (data_o_flush_timeout),
      .flush_active       (data_o_flush_active[0+i]),
      .flush_done         (data_o_flush_done[0+i])
    );

endmodule 
