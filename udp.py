from socket import *
import struct
import select
import time

import spi

# Base class of a network-ified FPGA.
# For multiple FPGA comms, this really needs to be turned into
# some sort of a server thing.
class UDPFPGA:
	def __init__(self):
		self.client = socket(AF_INET, SOCK_DGRAM)
		self.client.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
		self.server = socket(AF_INET, SOCK_DGRAM)
		# this makes it so we can't talk to multiple things right now
		# deal with this later
		self.server.bind(('0.0.0.0', 18521))
		self.target = None
		self.server.setblocking(0)
	
	def empty_socket(self):
		try:
			while True:
				self.server.recv(1024)
		except:
			pass

	def assign_ip(self, dna, ip):
		if len(ip) > 4:
			ip=inet_aton(ip)
		self.client.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
		self.empty_socket()
		self.client.sendto(self.static_ip_command(dna, ip), ("255.255.255.255", 18520))
		self.client.setsockopt(SOL_SOCKET, SO_BROADCAST, 0)
		while True:
			ready = select.select([self.server], [], [], 2)
			if ready[0]:
				data = self.server.recv(4096)
				cmd = struct.unpack('2sB', data[0:3])
				if cmd[0]=='SI' and cmd[1]==0:
					vals = struct.unpack('!Q', data[3:11])
					if vals[0] == dna:
						self.target = (ip, 18520)
						self.target_dna = vals[0]
						return True
					else:
						print "Got a response from unaddressed target: %x" % dna
						return False
				else:
					print "No acknowledgement of IP address assignment."
					print "Check IP address "		

	def connect(self, dna=None):
		if self.target == None:
			self.client.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
			self.empty_socket()
			self.client.sendto(self.id_command(), ("255.255.255.255", 18520))
			self.client.setsockopt(SOL_SOCKET, SO_BROADCAST, 0)
			while True:
				ready = select.select([self.server], [],[], 2)
				if ready[0]:
					data = self.server.recv(4096)
					# TODO: check length here
					cmd = struct.unpack('2sB', data[0:3])
					if cmd[0]=='ID' and cmd[1]==0:
						target_ip = inet_ntoa(data[3:7])
						vals = struct.unpack('!Q', data[7:15])
						if dna != None:
							if vals[0] == dna:
								self.target = (target_ip, 18520)
								self.target_dna = vals[0]
								return True
						else:
							self.target = (target_ip, 18520)
							self.target_dna = vals[0]
							return True
				else:
					print "Failed to find device."
					return False
	
	def readMultiple(self, addr, numReads):
		if numReads > 16:
			return None
		if self.target != None:
			self.empty_socket()
			self.client.sendto(self.read_command(addr, numReads), self.target)
			while True:
				ready = select.select([self.server], [], [], 2)
				if ready[0]:
					data = self.server.recv(4096)
					# TODO: check length here
					cmd = struct.unpack('2sB', data[0:3])
					if cmd[0]=='RD' and cmd[1]==0:
						respAddr = struct.unpack('!H',data[3:5])
						if	respAddr[0] != addr:
							# TODO: this should really be throwing an exception
							print "Got response for wrong address!"
							return None
						respData=[]
						data=data[5:]
						for i in xrange(numReads):
							respData.extend(struct.unpack('!L',data[0:4]))
							data=data[4:]
						return respData
				else:
					# TODO: this should really be throwing an exception
					print "No response!"
					return None
		else:
			# TODO: this should really be throwing an exception
			print "No target, use connect first"
			return None							
	
	
	def read(self, addr):
		rd = self.readMultiple(addr, 1)
		return rd[0]

	def write(self, addr, data, no_acknowledge=False):
		if type(data) is not list: data = [ data ]
		if self.target != None:
			self.empty_socket()
			self.client.sendto(self.write_command(addr, data), self.target)
			if no_acknowledge == True:
				return
			while True:
				ready = select.select([self.server], [], [], 2)
				if ready[0]:
					data = self.server.recv(4096)
					# TODO: check length here
					cmd = struct.unpack('2sB', data[0:3])
					if cmd[0]=='WR' and cmd[1]==0:
						respAddr = struct.unpack('!H',data[3:5])
						if	respAddr[0] != addr:
							# TODO: this should really be throwing an exception
							print "Got response for wrong address!"
							return 0
						respNum = struct.unpack('B',data[5])
						return respNum
				else:
					# TODO: this should really be throwing an exception
					print "No response!"
					return 0
		else:
			# TODO: this should really be throwing an exception
			print "No target, use connect first"
			return 0						

	def static_ip_command(self, dna, ip):
		str = struct.pack('!ccbQ', 'S', 'I', 0, dna) + ip
		return str
		
	def id_command(self):
		str = struct.pack('!ccb', 'I', 'D', 0 )
		return str

	def write_command(self, addr, data):
		nwr = len(data)
		cstr = struct.pack('!ccbH','W','R',0, addr)
		for i in xrange(nwr):
			cstr = cstr + struct.pack('!I', data[i])		
		return cstr

	def read_command(self, addr, numBytes=1):
		str = struct.pack('!ccbHB','R','D',0, addr, numBytes)
		return str	

class TOFProto(UDPFPGA):
	def __init__(self, dna=None, ip=None):
		UDPFPGA.__init__(self)
		if ip != None:
			UDPFPGA.assign_ip(self, dna, ip)
		elif UDPFPGA.connect(self, dna):
			print "Connected to device %x" % self.target_dna
		self.resetI2C()
		self.spi = spi.SPI(spi.AXIQuadSPI(self, 0x3000, 0))		
	
	def readTemperature(self):
		raw = self.read(0x1200)
		raw = raw >> 4
		return (raw*503.975)/4096 - 273.15
		
	def setLED(self, ledval):
		self.write(0x0000, ledval)
		
	# Call this function at initialization to make sure
	# we understand what state we're in.
	def resetI2C(self):
		self.write(0x2040, 0xA)
		self.write(0x2100, 0x1)
		
	def writeI2C(self, dev, data):
		# I2C write process (to a device with 7 bit address 'dev')
		
		# NOTE SEVEN BIT ADDRESS! Not 8-bit!
		
		# Try using the dynamic controller.
		# write dev to TX_FIFO (0x2108) with start bit set (and stop if no bytes).
		# write data to TX_FIFO. Last byte has stop bit set.
		# read ISR. If int(2) is set, transmit is done. If int(1) is set, got a nack.
		if len(data) == 0:
			self.write(0x2108, (dev << 1) | 0x300)
		else:
			self.write(0x2108, (dev << 1) | 0x100)
			# set the last bit in the data
			data[-1] = data[-1] | 0x200
			self.write(0x2108, data)
		# now read until something is set in the ISR
		val = None
		while True:
			val = self.read(0x2020)
			if val & 0x6:
				break
		
		self.write(0x2020, val)				
		if val & 0x2:
			print "TX error"
			# reset FIFO, I guess...?
			self.write(0x2100, 0x2)
			self.write(0x2100, 0x0)
			return False
		else:
			return True

	def readI2C(self, dev, len):
		# I2C read process (to a device with 7 bit address 'dev')
		# Read len bytes.
		# Write address + start bit (0x100)
		if len==0:
			return []
		self.write(0x2108, (dev<<1) | 0x100)
		self.write(0x2108, len | 0x200)
		# now read until RX_FIFO not empty
		rxd=[]
		while len(rxd)<len:
			val = self.read(0x2104)
			if not (val & 0x40):
				rxd.append(self.read(0x210C))
		# I need to check somehow that things haven't gone horribly wrong.
		return rxd
		
		
	def reprogram(self, filename):
		self.spi.program_mcs(filename)
		self.reloadFPGA()		
		
	# Issue an FPGA reload through the ICAP.
	def reloadFPGA(self, address=0):
		# step 1: write instruction to FIFO register )-(0x4100)
		# step 2: write 0x1 into control register to initiate write (0x410C)
		# from UG470		
		data = [ 0xFFFFFFFF, 0xAA995566, 0x20000000, 0x30020001, address, 0x30008001, 0x0000000F, 0x20000000 ]
		self.write(0x4100, data)
		# This write has to be a write without acknowledge.
		self.write(0x410C, 0x1, no_acknowledge=True)
		# poof goes the FPGA
		print "FPGA reloaded."
# base addrs: 0000 = gpio
#             1000 = xadc
#             2000 = IIC
#             3000 = quad spi
#             4000 = ICAP
if __name__	== "__main__":
	dev = TOFProto()
	dev.spi.identify()
	dev.spi.program_mcs("eth_test_v2_top.mcs")

#spidata = [0]*21
#spidata[0] = 0x9E
#spidata=[0x9E, 0, 0]
#rd = dev.SPI(spidata)
#print rd
#print "Temperature: %f" % dev.readTemperature()
#dev.resetI2C()
#print "I2C ISR: %x" % dev.read(0x2020)
#print "I2C SR: %x " % dev.read(0x2104)
#print dev.writeI2C(0x20, [0x00])
#print "I2C ISR: %x" % dev.read(0x2020)
#print "I2C SR: %x " % dev.read(0x2104)
#print "I2C SR: %x " % dev.read(0x2104)
#print "I2C SR: %x " % dev.read(0x2104)

#cs = socket(AF_INET, SOCK_DGRAM)
#cs.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
#cs.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
#ss = socket(AF_INET, SOCK_DGRAM)
#ss.bind((gethostname(), 18521))
#ss.setblocking(0)
#str = struct.pack('!ccb', 'I', 'D', 0)
#cs.sendto(str, ("255.255.255.255", 18520))

#data = None

# This won't work for multiple respondents,
# figure that out later.
#target_ip = None
#while True:
#	ready = select.select([ss], [], [], 2)
#	if ready[0]:
#		data = ss.recv(4096)
#		cmd = struct.unpack('2sB', data[0:3])
#		if cmd[0]=='ID' and cmd[1]==0:
#			target_ip = inet_ntoa(data[3:7])
#			dna = struct.unpack('!Q', data[8:15]+"\0")
#			print "Got ID: device %d at %s" % (dna[0], target_ip)
#			break
#if target_ip == None:
#	print "Could not find any devices."
#	quit()
#
#target = (target_ip, 18520)
#
# The LED register is at 0x00.
# Need to send WR(0)(addr)(data)
#
#for i in xrange(16):	
#	cs.sendto(write_command(0,i), target)
#	time.sleep(1)

