
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

endmodule 
