from parcing import ParcingSoccer

if __name__ == "__main__":
	parser = ParcingSoccer()
	for event in parser.run(interval=8):
		print(event)
