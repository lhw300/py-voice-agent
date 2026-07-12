class MyStack:
    def __init__(self):
        self.index=-1
        self.MAX=2
        self.str_arr=[None]*self.MAX

    def push(self,data:str):
        if self.index+1 == self.MAX:
            raise ValueError("stack full")
        self.index+=1
        self.str_arr[self.index]=data

    def size(self)->int:
        return self.index+1
    def pop(self)->str:
        if self.index == -1:
            raise ValueError("stack empty")
        mydata=self.str_arr[self.index]
        self.index-=1
        return mydata
if __name__ == "__main__":
    ms=MyStack()
    try:
        ms.push("a")
        ms.push("b")
        ms.push("b")
        print("1=",ms.pop())
        print("2=",ms.pop())
    except Exception as e:
        print(f"unknow err{e} ")