library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity del4 is
end entity;


architecture sim of del4 is

  component del_wrap is 
    generic
    (
      log : integer := 23;
      log_balh :  integer := 3
    )
    port
    (
      clk_in : in std_logic;
      debug_slv_in : out std_logic_vector(31 downto 0);
      debug_uns : out unsigned(7 downto 0);
      debug_sl : out std_logic := '0';
      debug_sl2 : out std_logic
    );
  end component;


begin

  i_del_wrap : del_wrap 
    generic map
    (
      log  => 3
      log_balh => 20
    )
    port map
    (
      clk_in => clk_in,
      debug_slv => debug_slv,
      debug_uns => debug_uns,
      debug_sl  => debug_sl ,
      debug_sl2 => debug_sl2
    );
  end component;


end architecture;
