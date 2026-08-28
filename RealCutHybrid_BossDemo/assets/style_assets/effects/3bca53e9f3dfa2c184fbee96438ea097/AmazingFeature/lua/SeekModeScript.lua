local exports = exports or {}
local SeekModeScript = SeekModeScript or {}
SeekModeScript.__index = SeekModeScript

---@class SeekModeScript : ScriptComponent
---@field progress number [UI(Range={0, 1}, Slider)]
---@field duration number
---@field autoPlay boolean

function SeekModeScript.new(construct, ...)
    local self = setmetatable({}, SeekModeScript)

    self.progress = 0.0
    self.autoPlay = true
    self.curTime = 0.0
    self.duration = 1.0
    if construct and SeekModeScript.constructor then SeekModeScript.constructor(self, ...) end
    return self
end

function SeekModeScript:constructor()
    
end

function SeekModeScript:onStart(comp)
    
    self.EntityMR = comp.entity.scene:findEntityBy("Entity01"):getComponent("MeshRenderer")
    self.Mat = comp.entity.scene:findEntityBy("Entity01"):getComponent("MeshRenderer").material

    -- self.input1 = comp.entity.scene.assetMgr:SyncLoad("image/1.png")
    -- self.input2 = comp.entity.scene.assetMgr:SyncLoad("image/2.png")
end

function SeekModeScript:onUpdate(comp, deltaTime)
     -- self.progress
     if self.autoPlay == true then
        self.curTime = (self.curTime + deltaTime) % self.duration
        self.progress = self.curTime / self.duration
    else
        self.curTime = 0
    end


    local input1 = Amaz.BuiltinObject.getUserTexture("#TransitionInput0")
    local input2 = Amaz.BuiltinObject.getUserTexture("#TransitionInput1")
    if input1 and input2 then
        self.input1 = input1
        self.input2 = input2
        self.curTime = Amaz.Input.frameTimestamp;
        self.progress = Amaz.Input.frameTimestamp;
    end

    if self.progress < 0.5 then
        self.Mat:setTex("inputImageTexture" , self.input1)
        self.Mat:setFloat("progress" , self.progress * 2.0)
    else
        self.Mat:setTex("inputImageTexture" , self.input2)
        self.Mat:setFloat("progress" , (1 - self.progress) * 2.0)
        
    end
    
end

exports.SeekModeScript = SeekModeScript
return exports
